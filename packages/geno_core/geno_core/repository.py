from __future__ import annotations

import csv
import hashlib
import json
import re
from contextlib import nullcontext
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Any, Protocol
from urllib.parse import urlencode, unquote, urlparse
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from geno_core.audit import build_audit_event
from geno_core.email_delivery import (
    render_project_member_invitation_email,
    render_runtime_notification_email,
    runtime_email_body_hash,
    send_runtime_email_message,
)
from geno_core.email_preferences import (
    RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_MANAGE_ACTION,
    RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_RESUBSCRIBE_ACTION,
    RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_UNSUBSCRIBE_ACTION,
    RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_VERSION,
    runtime_notification_email_preference_token_hash,
    sign_runtime_notification_email_preference_token,
)
from geno_core.models import (
    ActionRecommendation,
    AnswerAnalysis,
    AuditEvent,
    CitationGraphResult,
    CollectionFailureRecord,
    CollectionRunSummary,
    EntityAliasCandidateAssignmentActionInput,
    EntityAliasCandidateAssignmentBatchActionInput,
    EntityAliasCandidateAssignmentReassignmentInput,
    ContentDraft,
    EntityAliasCandidateAssignmentInput,
    EntityAliasAssignmentDispatchApplyInput,
    EntityAliasAssignmentDispatchPlanInput,
    EntityAliasCandidateReviewInput,
    EntityAliasInput,
    IntegrationConnector,
    LocalizedKnowledgeFact,
    ManualDistributionRecord,
    ProjectBootstrap,
    RawEvidenceRecord,
    ReportExport,
    RetestComparison,
    RetestSchedule,
    RuntimeActionPlan,
    RuntimeActionPlanPage,
    RuntimeActionRecommendationUpdate,
    RuntimeActionRecommendationUpdateInput,
    RuntimeAlertEvent,
    RuntimeAlertEventInput,
    RuntimeAlertItem,
    RuntimeAlertNotificationResult,
    RuntimeAlertPage,
    RuntimeAuditEvent,
    RuntimeAuditEventExport,
    RuntimeAuditEventPage,
    RuntimeCitationGraph,
    RuntimeCitationGraphNode,
    RuntimeCitationGraphPage,
    RuntimeContentDraft,
    RuntimeContentDraftReview,
    RuntimeContentDraftReviewInput,
    RuntimeContentEngine,
    RuntimeContentEnginePage,
    RuntimeCollectionRun,
    RuntimeCollectionRunPage,
    RuntimeEvidenceExport,
    RuntimeEvidenceAsset,
    RuntimeEvidenceAssetInput,
    RuntimeEvidencePage,
    RuntimeEvidenceRun,
    RuntimeEntityAlias,
    RuntimeEntityAliasAssignmentEscalationResult,
    RuntimeEntityAliasAssignmentNotificationResult,
    RuntimeEntityAliasAssignmentReassignmentResult,
    RuntimeEntityAliasAssignmentBatchActionResult,
    RuntimeEntityAliasAssignmentDispatchApplyResult,
    RuntimeEntityAliasAssignmentDispatchPlan,
    RuntimeEntityAliasAssignmentWorkbench,
    RuntimeEntityAliasAssignmentWorkloadSummary,
    RuntimeEntityAliasCandidate,
    RuntimeEntityAliasCandidateAssignmentQueueStats,
    RuntimeEntityAliasCandidateBatchReviewResult,
    RuntimeEntityAliasCandidatePage,
    RuntimeEntityAliasCandidateReview,
    RuntimeEntityAliasCandidateReviewPage,
    RuntimeEntityAliasPage,
    RuntimeFidelityCheck,
    RuntimeFidelityCheckPage,
    RuntimeFidelityTrend,
    RuntimeFidelityTrendPoint,
    RuntimeHumanReviewInput,
    RuntimeHumanReviewPage,
    RuntimeHumanReviewQueueItem,
    RuntimeHumanReviewQueuePage,
    RuntimeHumanReviewRecord,
    RuntimeKnowledgeSearchPage,
    RuntimeKnowledgeSearchResult,
    RuntimeKnowledgeFactImportInput,
    RuntimeKnowledgeFactImportResult,
    RuntimeKnowledgeApplicationPage,
    RuntimeKnowledgeApplicationRequest,
    RuntimeKnowledgeApplicationResult,
    RuntimeKnowledgeDocument,
    RuntimeKnowledgeDocumentCrawlInput,
    RuntimeKnowledgeDocumentExtractionInput,
    RuntimeKnowledgeDocumentInput,
    RuntimeKnowledgeFactReviewInput,
    RuntimeManualDistributionBackfill,
    RuntimeManualDistributionBackfillInput,
    RuntimeNotification,
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
    RuntimeNotificationSubscription,
    RuntimeNotificationSubscriptionInput,
    RuntimeNotificationSubscriptionPage,
    RuntimeNotificationStatusInput,
    RuntimeProjectBrandAsset,
    RuntimeProjectBrandKit,
    RuntimeProjectBrandKitInput,
    RuntimeProjectBrandAssetInput,
    RuntimeProjectBrandAssetPage,
    RuntimeProjectBrandAssetScanInput,
    RuntimeProjectBrandAssetActivationInput,
    RuntimeProjectBrandAssetVersion,
    RuntimeProjectBrandAssetVersionPage,
    RuntimeProjectBrandLogoUpload,
    RuntimeProject,
    RuntimeProjectBrandEntityInput,
    RuntimeProjectLifecycleEvent,
    RuntimeProjectLifecycleEventExport,
    RuntimeProjectLifecycleEventPage,
    RuntimeProjectCompetitorEntityInput,
    RuntimeProjectEntity,
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
    RuntimeProjectPage,
    RuntimeProjectActionInput,
    RuntimeProjectUpdateInput,
    RuntimePromptImportHistoryItem,
    RuntimePromptImportHistoryPage,
    RuntimePromptImportInput,
    RuntimePromptImportResult,
    RuntimePromptCandidateImportInput,
    RuntimePromptCandidateReviewInput,
    RuntimePromptPage,
    RuntimePromptUpdateInput,
    RuntimeReportArtifact,
    RuntimeReportExportJob,
    RuntimeReportExportJobInput,
    RuntimeReportExportJobPage,
    RuntimeReportExportJobQueueStats,
    RuntimeReportExportJobStatusInput,
    RuntimeReportExport,
    RuntimeReportExportPage,
    RuntimeReportManagementInput,
    RuntimeSavedView,
    RuntimeSavedViewInput,
    RuntimeSavedViewPage,
    RuntimeScoreWeightConfig,
    RuntimeScoreWeightConfigInput,
    RuntimeScoreWeightProfile,
    RuntimeScoreWeightProfileInput,
    RuntimeScoreWeightProfilePage,
    RuntimeScoreSnapshot,
    RuntimeScoreSnapshotPage,
    RuntimeScoreSnapshotRun,
    RuntimeTraceabilityDetail,
    ScoreContribution,
    TraceabilityBundle,
    VisibilityScoreSnapshot,
)
from geno_core.report import (
    build_report_audit_summary,
    build_report_methodology_disclosure,
    build_score_rate_methodology,
    methodology_rows_from_runtime_answer_runs,
    render_markdown_pdf,
    render_audit_summary_lines,
    render_methodology_disclosure_lines,
)
from geno_core.runtime_project_access_repository import RuntimeProjectAccessRepositoryMixin
from geno_core.fidelity import build_runtime_fidelity_check
from geno_core.scoring import get_score_formula, list_score_weight_profiles, normalize_score_weights
from geno_core.knowledge import (
    KNOWLEDGE_EMBEDDING_MODEL,
    KNOWLEDGE_FACT_APPROVED_STATUS,
    embed_knowledge_text,
    knowledge_fact_content_hash,
    knowledge_fact_text,
)
from geno_core.knowledge_application import (
    DEEPSEEK_DEFAULT_MODEL,
    DOCUMENT_STATUS_CRAWLED,
    DOCUMENT_STATUS_EXTRACTED,
    DOCUMENT_STATUS_FAILED,
    DOCUMENT_STATUS_QUEUED,
    GEO_CONTENT_DRAFT_PROMPT_VERSION,
    KNOWLEDGE_APPLICATION_PIPELINE_VERSION,
    PROMPT_CANDIDATE_APPROVED,
    PROMPT_CANDIDATE_ARCHIVED,
    PROMPT_CANDIDATE_IMPORTED,
    PROMPT_CANDIDATE_PENDING,
    PROMPT_CANDIDATE_REJECTED,
    build_knowledge_application_artifacts,
    crawl_public_knowledge_url,
    deepseek_extract_knowledge_facts,
    deepseek_generate_knowledge_application,
    extract_knowledge_facts_from_document,
    load_deepseek_api_key,
    normalize_knowledge_url,
    stable_knowledge_id,
)


class DbCursor(Protocol):
    def execute(self, sql: str, params: tuple[object, ...] = ()) -> Any: ...

    def fetchone(self) -> Any: ...

    def fetchall(self) -> Any: ...

    def __enter__(self) -> "DbCursor": ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...


class DbConnection(Protocol):
    def cursor(self) -> DbCursor: ...

    def commit(self) -> None: ...


def _json_compatible(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _json_payload(value: object) -> object:
    if is_dataclass(value):
        value = asdict(value)
    payload = _json_compatible(value)
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return payload
    return Jsonb(payload)


def _contains_forbidden_email_feedback_project_suppression_metadata(value: object) -> bool:
    forbidden_keys = {
        "recipient",
        "raw_recipient",
        "email",
        "email_address",
        "provider_event_id",
        "raw_provider_event_id",
        "secret",
        "raw_secret",
        "token",
        "raw_token",
    }
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in forbidden_keys or normalized_key.endswith("_secret") or normalized_key.startswith("raw_"):
                return True
            if _contains_forbidden_email_feedback_project_suppression_metadata(child):
                return True
    elif isinstance(value, (list, tuple, set)):
        return any(_contains_forbidden_email_feedback_project_suppression_metadata(child) for child in value)
    return False


def _runtime_notification_slack_payload(
    *,
    notification: dict[str, Any],
    subscription: dict[str, Any],
    threshold: str,
) -> dict[str, Any]:
    severity = str(notification.get("severity") or "info").strip().lower()
    notification_type = str(notification.get("notification_type") or "runtime_notification").strip()
    title = str(notification.get("title") or "GENO runtime notification").strip()
    message = str(notification.get("message") or "").strip()
    target_type = str(notification.get("target_type") or "target").strip()
    target_id = str(notification.get("target_id") or "").strip()
    text = f"[{severity.upper()}] {title}"
    if message:
        text = f"{text}: {message}"
    fields = [
        {"type": "mrkdwn", "text": f"*Type*\n{notification_type}"},
        {"type": "mrkdwn", "text": f"*Severity*\n{severity}"},
        {"type": "mrkdwn", "text": f"*Target*\n{target_type}"},
        {"type": "mrkdwn", "text": f"*Threshold*\n{threshold}"},
    ]
    if target_id:
        fields.append({"type": "mrkdwn", "text": f"*Target ID*\n`{target_id}`"})
    return {
        "text": text,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{title}*\n{message or text}"},
            },
            {"type": "section", "fields": fields[:10]},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"GENO runtime · notification `{notification.get('id')}` · "
                            f"subscription `{subscription.get('id')}`"
                        ),
                    }
                ],
            },
        ],
        "metadata": {
            "event_type": "geno_runtime_notification",
            "event_payload": {
                "notification_id": str(notification.get("id")),
                "notification_type": notification_type,
                "project_id": str(notification.get("project_id")),
                "target_type": target_type,
                "target_id": target_id,
            },
        },
    }


def _runtime_notification_email_recipients(endpoint_url: str) -> list[str]:
    parsed = urlparse(endpoint_url)
    if parsed.scheme != "mailto":
        return []
    return [
        unquote(recipient.strip())
        for recipient in parsed.path.split(",")
        if recipient and recipient.strip()
    ]


def _normalize_runtime_email_address(value: object) -> str:
    return " ".join(str(value).replace("\r", "\n").split()).strip().lower()


def _runtime_notification_email_metadata(subscription: dict[str, Any]) -> dict[str, Any]:
    metadata = subscription.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _metadata_header_value(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    if value is None:
        return ""
    return " ".join(str(value).replace("\r", "\n").split()).strip()


def _metadata_http_url(metadata: dict[str, Any], key: str) -> str:
    raw_url = _metadata_header_value(metadata, key)
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return raw_url
    return ""


def _metadata_mailto_url(metadata: dict[str, Any], key: str) -> str:
    raw_url = _metadata_header_value(metadata, key)
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    if parsed.scheme == "mailto" and parsed.path:
        return raw_url
    if "@" in raw_url and not parsed.scheme and not any(separator in raw_url for separator in " <>"):
        return f"mailto:{raw_url}"
    return ""


def _metadata_email_values(metadata: dict[str, Any], key: str) -> tuple[str, ...]:
    raw_value = metadata.get(key)
    if raw_value is None:
        return ()
    values: list[object]
    if isinstance(raw_value, str):
        values = raw_value.split(",")
    elif isinstance(raw_value, (list, tuple, set)):
        values = list(raw_value)
    else:
        values = [raw_value]
    normalized = tuple(
        email
        for email in (_normalize_runtime_email_address(value) for value in values)
        if email and "@" in email
    )
    return tuple(dict.fromkeys(normalized))


def _metadata_sha256_values(metadata: dict[str, Any], key: str) -> tuple[str, ...]:
    raw_value = metadata.get(key)
    if raw_value is None:
        return ()
    values: list[object]
    if isinstance(raw_value, str):
        values = raw_value.split(",")
    elif isinstance(raw_value, (list, tuple, set)):
        values = list(raw_value)
    else:
        values = [raw_value]
    hashes: list[str] = []
    for value in values:
        normalized = str(value).strip().lower()
        if len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized):
            hashes.append(normalized)
    return tuple(dict.fromkeys(hashes))


def _runtime_notification_email_control_metadata(metadata: dict[str, Any]) -> dict[str, str]:
    controls = {
        "email_unsubscribe_url": _metadata_http_url(metadata, "email_unsubscribe_url"),
        "email_unsubscribe_mailto": _metadata_mailto_url(metadata, "email_unsubscribe_mailto"),
        "email_preferences_url": _metadata_http_url(metadata, "email_preferences_url"),
    }
    return {key: value for key, value in controls.items() if value}


def _runtime_notification_email_control_hashes(controls: dict[str, str]) -> dict[str, str]:
    return {f"{key}_hash": runtime_email_body_hash(value) for key, value in controls.items() if value}


def _runtime_notification_email_suppression_hashes(recipients: tuple[str, ...] | list[str]) -> list[str]:
    return [
        runtime_email_body_hash(normalized)
        for normalized in (_normalize_runtime_email_address(recipient) for recipient in recipients)
        if normalized
    ]


def _runtime_notification_configured_suppression_hashes(metadata: dict[str, Any]) -> tuple[str, ...]:
    raw_recipient_hashes = _runtime_notification_email_suppression_hashes(
        _metadata_email_values(metadata, "email_suppressed_recipients")
    )
    configured_hashes = _metadata_sha256_values(metadata, "email_suppressed_recipient_hashes")
    return tuple(dict.fromkeys([*raw_recipient_hashes, *configured_hashes]))


def _sha256_hex_or_none(value: str | None, *, field_name: str) -> str | None:
    normalized = (value or "").strip().lower()
    if not normalized:
        return None
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{field_name} must be a lowercase sha256 hex digest")
    return normalized


def _runtime_notification_email_payload(
    *,
    notification: dict[str, Any],
    subscription: dict[str, Any],
    threshold: str,
    project_suppression_hashes: tuple[str, ...] = (),
    preference_base_url: str = "",
    preference_token_secret: str = "",
    preference_token_ttl_seconds: int = 2_592_000,
) -> dict[str, Any]:
    severity = str(notification.get("severity") or "info").strip().lower()
    notification_type = str(notification.get("notification_type") or "runtime_notification").strip()
    title = str(notification.get("title") or "GENO runtime notification").strip()
    message = str(notification.get("message") or "").strip()
    target_type = str(notification.get("target_type") or "target").strip()
    target_id = str(notification.get("target_id") or "").strip()
    subscription_metadata = _runtime_notification_email_metadata(subscription)
    control_metadata = _runtime_notification_email_control_metadata(subscription_metadata)
    original_recipients = tuple(_runtime_notification_email_recipients(str(subscription.get("endpoint_url") or "")))
    suppressed_recipients = _metadata_email_values(subscription_metadata, "email_suppressed_recipients")
    suppressed_lookup = set(suppressed_recipients)
    subscription_suppression_hashes = _runtime_notification_configured_suppression_hashes(subscription_metadata)
    project_suppression_hashes = tuple(dict.fromkeys(project_suppression_hashes))
    configured_suppression_hashes = tuple(dict.fromkeys([*subscription_suppression_hashes, *project_suppression_hashes]))
    configured_suppression_hash_lookup = set(configured_suppression_hashes)
    filtered_recipients: list[str] = []
    suppressed_matched_hashes: list[str] = []
    for recipient in original_recipients:
        normalized_recipient = _normalize_runtime_email_address(recipient)
        recipient_hash = runtime_email_body_hash(normalized_recipient) if normalized_recipient else ""
        if normalized_recipient in suppressed_lookup or recipient_hash in configured_suppression_hash_lookup:
            if recipient_hash:
                suppressed_matched_hashes.append(recipient_hash)
            continue
        filtered_recipients.append(recipient)
    manage_preferences_url = ""
    manage_token_hash = ""
    tokenized_unsubscribe_url = ""
    preference_token_hash = ""
    preference_token_reason = ""
    normalized_preference_base_url = preference_base_url.strip()
    can_issue_recipient_token = bool(preference_token_secret and len(filtered_recipients) == 1)
    if can_issue_recipient_token:
        recipient_hash = runtime_email_body_hash(_normalize_runtime_email_address(filtered_recipients[0]))
        delivery_id = str(
            _stable_id(
                "runtime-notification-delivery",
                str(notification.get("id")),
                str(subscription.get("id")),
            )
        )
    else:
        recipient_hash = ""
        delivery_id = ""
    if can_issue_recipient_token and normalized_preference_base_url:
        preference_token = sign_runtime_notification_email_preference_token(
            secret=preference_token_secret,
            project_id=str(notification.get("project_id")),
            delivery_id=delivery_id,
            notification_id=str(notification.get("id")),
            subscription_id=str(subscription.get("id")),
            recipient_hash=recipient_hash,
            ttl_seconds=preference_token_ttl_seconds,
        )
        preference_token_hash = runtime_notification_email_preference_token_hash(preference_token)
        separator = "&" if "?" in normalized_preference_base_url else "?"
        tokenized_unsubscribe_url = (
            f"{normalized_preference_base_url}{separator}"
            f"{urlencode({'token': preference_token, 'action': RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_UNSUBSCRIBE_ACTION})}"
        )
    elif preference_token_secret and normalized_preference_base_url:
        preference_token_reason = "requires_single_filtered_recipient"
    raw_preferences_url = control_metadata.get("email_preferences_url") or ""
    if can_issue_recipient_token and raw_preferences_url:
        manage_token = sign_runtime_notification_email_preference_token(
            secret=preference_token_secret,
            action=RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_MANAGE_ACTION,
            project_id=str(notification.get("project_id")),
            delivery_id=delivery_id,
            notification_id=str(notification.get("id")),
            subscription_id=str(subscription.get("id")),
            recipient_hash=recipient_hash,
            ttl_seconds=preference_token_ttl_seconds,
        )
        manage_token_hash = runtime_notification_email_preference_token_hash(manage_token)
        separator = "&" if "?" in raw_preferences_url else "?"
        manage_preferences_url = (
            f"{raw_preferences_url}{separator}"
            f"{urlencode({'token': manage_token, 'action': RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_MANAGE_ACTION})}"
        )
    rendered_email = render_runtime_notification_email(
        notification_id=str(notification.get("id")),
        project_id=str(notification.get("project_id")),
        subscription_id=str(subscription.get("id")),
        notification_type=notification_type,
        severity=severity,
        threshold=threshold,
        target_type=target_type,
        target_id=target_id,
        title=title,
        message=message,
        unsubscribe_url=(
            tokenized_unsubscribe_url
            or control_metadata.get("email_unsubscribe_url")
            or control_metadata.get("email_unsubscribe_mailto")
        ),
        preferences_url=manage_preferences_url or control_metadata.get("email_preferences_url"),
    )
    headers = {
        "X-GENO-Notification-Id": str(notification.get("id")),
        "X-GENO-Project-Id": str(notification.get("project_id")),
        "X-GENO-Notification-Type": notification_type,
        "X-GENO-Severity": severity,
        "X-GENO-Email-Template-Version": rendered_email.template_version,
    }
    reply_to = _metadata_header_value(subscription_metadata, "email_reply_to")
    if reply_to:
        headers["Reply-To"] = reply_to
    unsubscribe_header_urls = [
        value
        for value in (
            tokenized_unsubscribe_url or control_metadata.get("email_unsubscribe_url"),
            control_metadata.get("email_unsubscribe_mailto"),
        )
        if value
    ]
    if unsubscribe_header_urls:
        headers["List-Unsubscribe"] = ", ".join(f"<{value}>" for value in unsubscribe_header_urls)
        if tokenized_unsubscribe_url or control_metadata.get("email_unsubscribe_url"):
            headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    if manage_preferences_url or control_metadata.get("email_preferences_url"):
        headers["X-GENO-Notification-Preferences-Url"] = manage_preferences_url or control_metadata["email_preferences_url"]
    control_hashes = _runtime_notification_email_control_hashes(control_metadata)
    reply_to_hash = runtime_email_body_hash(reply_to) if reply_to else ""
    return {
        "to": list(filtered_recipients),
        "subject": rendered_email.subject,
        "text": rendered_email.text,
        "headers": headers,
        "metadata": {
            "notification_id": str(notification.get("id")),
            "notification_type": notification_type,
            "project_id": str(notification.get("project_id")),
            "target_type": target_type,
            "target_id": target_id,
            "email_template_version": rendered_email.template_version,
            "email_template_hash": rendered_email.template_hash,
            "email_subject_hash": rendered_email.subject_hash,
            "email_body_hash": rendered_email.body_hash,
            "email_reply_to_hash": reply_to_hash,
            "email_control_hashes": control_hashes,
            "email_tokenized_unsubscribe_url_hash": runtime_email_body_hash(tokenized_unsubscribe_url)
            if tokenized_unsubscribe_url
            else "",
            "email_tokenized_preferences_url_hash": runtime_email_body_hash(manage_preferences_url)
            if manage_preferences_url
            else "",
            "email_preference_token_version": RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_VERSION
            if preference_token_hash or manage_token_hash
            else "",
            "email_preference_token_hash": preference_token_hash,
            "email_preference_token_action": RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_UNSUBSCRIBE_ACTION
            if preference_token_hash
            else "",
            "email_preference_manage_token_hash": manage_token_hash,
            "email_preference_manage_token_action": RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_MANAGE_ACTION
            if manage_token_hash
            else "",
            "email_preference_token_reason": preference_token_reason,
            "email_recipient_count": len(original_recipients),
            "email_filtered_recipient_count": len(filtered_recipients),
            "email_suppressed_recipient_hashes": list(dict.fromkeys(suppressed_matched_hashes)),
            "email_configured_suppression_hashes": list(configured_suppression_hashes),
            "email_subscription_suppression_hash_count": len(subscription_suppression_hashes),
            "email_project_suppression_hash_count": len(project_suppression_hashes),
            "email_project_suppression_hashes": list(project_suppression_hashes),
        },
    }


def _runtime_notification_delivery_payload(
    *,
    notification: dict[str, Any],
    subscription: dict[str, Any],
    notification_type: str,
    severity: str,
    threshold: str,
    channel: str,
    project_suppression_hashes: tuple[str, ...] = (),
    email_preference_base_url: str = "",
    email_preference_token_secret: str = "",
    email_preference_token_ttl_seconds: int = 2_592_000,
) -> dict[str, Any]:
    base_payload = {
        "notification": {
            "id": str(notification["id"]),
            "project_id": str(notification["project_id"]),
            "notification_type": notification_type,
            "severity": severity,
            "title": notification.get("title"),
            "message": notification.get("message"),
            "target_type": notification.get("target_type"),
            "target_id": notification.get("target_id"),
            "payload": notification.get("payload") or {},
            "created_at": notification.get("created_at"),
        },
        "subscription": {
            "id": str(subscription["id"]),
            "channel": channel,
            "severity_threshold": threshold,
        },
        "delivery_version": "runtime_notification_delivery_v1",
    }
    if channel == "slack":
        return {
            **base_payload,
            "slack": _runtime_notification_slack_payload(
                notification=notification,
                subscription=subscription,
                threshold=threshold,
            ),
            "delivery_version": "runtime_notification_delivery_slack_v1",
        }
    if channel == "email":
        return {
            **base_payload,
            "email": _runtime_notification_email_payload(
                notification=notification,
                subscription=subscription,
                threshold=threshold,
                project_suppression_hashes=project_suppression_hashes,
                preference_base_url=email_preference_base_url,
                preference_token_secret=email_preference_token_secret,
                preference_token_ttl_seconds=email_preference_token_ttl_seconds,
            ),
            "delivery_version": "runtime_notification_delivery_email_v1",
        }
    return base_payload


def _uuid_array(values: tuple[str, ...] | list[str]) -> list[object]:
    converted: list[object] = []
    for value in values:
        try:
            converted.append(UUID(str(value)))
        except (TypeError, ValueError):
            converted.append(str(value))
    return converted


def _uuid(value: str | None) -> object | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return str(value)


def _vector_literal(values: tuple[float, ...] | list[float]) -> str:
    return "[" + ",".join(str(round(float(value), 6)) for value in values) + "]"


def _datetime(value: datetime | None) -> datetime | None:
    return value


def _runtime_evidence_asset_content_hash(*, url: str, content_hash: str | None, metadata: object | None = None) -> str:
    if content_hash:
        return content_hash
    return hashlib.sha256(
        json.dumps(
            {
                "url": url,
                "metadata": _json_compatible(metadata or {}),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _llm_call_logs_from_analysis(analysis: AnswerAnalysis) -> tuple[dict[str, Any], ...]:
    comparison = analysis.parser_comparison or {}
    if not isinstance(comparison, dict):
        return ()
    candidates: list[object] = [comparison.get("llm_call_log")]
    secondary_result = comparison.get("secondary_result")
    if isinstance(secondary_result, dict):
        candidates.append(secondary_result.get("llm_call_log"))
    logs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for candidate in candidates:
        if is_dataclass(candidate):
            candidate = asdict(candidate)
        if not isinstance(candidate, dict):
            continue
        log_id = str(candidate.get("id") or "")
        if not log_id or log_id in seen_ids:
            continue
        seen_ids.add(log_id)
        logs.append(candidate)
    return tuple(logs)


def _row_dict(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return {key: _json_compatible(value) for key, value in row.items()}
    return {column: _json_compatible(row[index]) for index, column in enumerate(columns)}


def _rows_dict(rows: Any, columns: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    return tuple(_row_dict(row, columns) for row in rows)


def _coerce_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _first_ref(value: object, default: object = None) -> object:
    if isinstance(value, list):
        return value[0] if value else default
    return value if value is not None else default


def _latest_audit_event(events: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    if not events:
        return {}
    return max(
        events,
        key=lambda event: (
            _coerce_datetime(event.get("created_at")) or datetime.min.replace(tzinfo=UTC),
            str(event.get("id") or ""),
        ),
    )


def _hash_text_field(value: object) -> str:
    text = str(value or "")
    return _artifact_hash(text) if text else ""


def _pipe_join(values: object) -> str:
    if not isinstance(values, (list, tuple)):
        return ""
    return "|".join(str(value) for value in values if value is not None)


def _prompt_import_history(audit_event: dict[str, Any]) -> dict[str, Any]:
    input_refs = audit_event.get("input_refs") or {}
    output_refs = audit_event.get("output_refs") or {}
    prompt_question_ids = output_refs.get("prompt_question_ids") or []
    if not isinstance(prompt_question_ids, list):
        prompt_question_ids = [prompt_question_ids]
    source_format = str(_first_ref(input_refs.get("source_format"), "csv") or "csv")
    return {
        "id": audit_event.get("target_id"),
        "project_id": audit_event.get("project_id"),
        "actor_id": audit_event.get("actor_id"),
        "source_format": source_format,
        "source_filename": _first_ref(input_refs.get("source_filename")),
        "source_content_type": _first_ref(input_refs.get("source_content_type")),
        "csv_sha256": _first_ref(input_refs.get("csv_sha256")),
        "prompt_count": len(prompt_question_ids),
        "prompt_question_ids": prompt_question_ids,
        "method_version": audit_event.get("method_version"),
        "after_hash": audit_event.get("after_hash"),
        "created_at": audit_event.get("created_at"),
    }


def _runtime_collection_run_row(row: dict[str, Any]) -> dict[str, Any]:
    int_fields = (
        "planned_runs",
        "attempted_runs",
        "success_count",
        "failure_count",
        "total_duration_ms",
        "average_duration_ms",
    )
    float_fields = (
        "success_rate",
        "trigger_rate",
        "answer_present_rate",
        "total_cost",
        "average_cost_per_run",
    )
    normalized = dict(row)
    for field in int_fields:
        normalized[field] = int(normalized.get(field) or 0)
    for field in float_fields:
        normalized[field] = float(normalized.get(field) or 0.0)
    return normalized


ALERT_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _alert_severity(value: str) -> int:
    return ALERT_SEVERITY_RANK.get(value, 9)


def _score_contribution_by_name(rows: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("component_name")): row for row in rows if row.get("component_name")}


def _first_matching_action(
    actions: tuple[dict[str, Any], ...],
    *,
    source_gap_type: str,
) -> tuple[dict[str, Any], ...]:
    matched = tuple(action for action in actions if action.get("source_gap_type") == source_gap_type)
    return matched[:3]


def _answer_run_refs(answer_run_ids: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(answer_run_ids, list):
        return ()
    return tuple({"target_type": "answer_run", "target_id": str(value)} for value in answer_run_ids[:10])


def _analysis_sentiment_score(analysis: dict[str, Any]) -> float | None:
    payload = analysis.get("payload")
    if not isinstance(payload, dict):
        return None
    raw_score = payload.get("sentiment_score")
    if raw_score is None:
        return None
    try:
        return float(raw_score)
    except (TypeError, ValueError):
        return None


def _frozen_method_disclosure(report_export: dict[str, Any]) -> dict[str, Any] | None:
    disclosure = report_export.get("method_disclosure")
    return dict(disclosure) if isinstance(disclosure, dict) else None


def _runtime_method_disclosure(report: RuntimeReportExport) -> dict[str, Any]:
    rows = methodology_rows_from_runtime_answer_runs(report.answer_runs)
    disclosure = _frozen_method_disclosure(report.report_export)
    if disclosure is None:
        return build_report_methodology_disclosure(
            rows=rows,
            platform_weights_snapshot=dict(report.report_export.get("platform_weights_snapshot") or {}),
            audit_events=tuple(report.audit_events),
        )
    if "score_rate_denominators" not in disclosure:
        disclosure["score_rate_denominators"] = build_score_rate_methodology(rows)
    if "audit_summary" not in disclosure:
        disclosure["audit_summary"] = build_report_audit_summary(tuple(report.audit_events))
    return disclosure


REPORT_MANAGEMENT_STATUS_ALIASES = {
    "pending_review": "internal_review",
    "approved": "internal_review",
    "published": "client_ready",
    "revoked": "archived",
}


def _normalize_report_management_status(status: str) -> str:
    normalized = status.strip().lower()
    return REPORT_MANAGEMENT_STATUS_ALIASES.get(normalized, normalized)


RUNTIME_EVIDENCE_SORTS = {
    "collected_at_desc": "ar.collected_at DESC, ar.id DESC",
    "collected_at_asc": "ar.collected_at ASC, ar.id ASC",
    "cost_desc": "cc.total_cost DESC NULLS LAST, ar.collected_at DESC, ar.id DESC",
    "cost_asc": "cc.total_cost ASC NULLS LAST, ar.collected_at DESC, ar.id DESC",
    "citation_count_desc": "citation_counts.citation_count DESC NULLS LAST, ar.collected_at DESC, ar.id DESC",
    "audit_count_desc": "audit_counts.audit_event_count DESC NULLS LAST, ar.collected_at DESC, ar.id DESC",
}


def _runtime_evidence_sort(sort: str | None) -> tuple[str, str]:
    normalized = sort or "collected_at_desc"
    return normalized if normalized in RUNTIME_EVIDENCE_SORTS else "collected_at_desc", RUNTIME_EVIDENCE_SORTS.get(
        normalized, RUNTIME_EVIDENCE_SORTS["collected_at_desc"]
    )


def _stable_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(("geno", kind, *(str(part) for part in parts)))))


def _alias_host(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.netloc or parsed.path).strip().lower().removeprefix("www.")


COMMON_ALIAS_CITATION_HOST_SUFFIXES = (
    "amazon.com",
    "amazon.com.au",
    "facebook.com",
    "google.com",
    "instagram.com",
    "linkedin.com",
    "medium.com",
    "productreview.com.au",
    "reddit.com",
    "tiktok.com",
    "trustpilot.com",
    "wikipedia.org",
    "x.com",
    "youtube.com",
)


def _compact_alias_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _alias_terms(value: str) -> tuple[str, ...]:
    return tuple(term for term in re.findall(r"[a-z0-9]+", value.lower()) if len(term) >= 3)


def _camel_case_alias(value: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value).strip()


def _answer_text_contains_alias(answer_text: str, alias: str) -> bool:
    if not answer_text.strip() or not alias.strip():
        return False
    pattern = rf"(?<![A-Za-z0-9]){re.escape(alias.strip())}(?![A-Za-z0-9])"
    return re.search(pattern, answer_text, flags=re.IGNORECASE) is not None


def _answer_text_alias_candidates(*, canonical_name: str, answer_text: str) -> tuple[str, ...]:
    canonical = canonical_name.strip()
    if len(_compact_alias_token(canonical)) < 4:
        return ()
    base_aliases = {canonical}
    spaced = _camel_case_alias(canonical)
    if spaced and spaced.lower() != canonical.lower():
        base_aliases.add(spaced)
    variants: list[str] = []
    for base_alias in sorted(base_aliases, key=lambda item: (len(item), item.lower())):
        variants.extend((f"{base_alias} Australia", f"{base_alias} AU", base_alias))
    candidates: list[str] = []
    seen: set[str] = set()
    for alias in variants:
        key = alias.lower()
        if key in seen or not _answer_text_contains_alias(answer_text, alias):
            continue
        seen.add(key)
        candidates.append(alias)
    return tuple(candidates)


def _citation_host_matches_entity(*, host: str, canonical_name: str) -> bool:
    if not host:
        return False
    normalized_host = _alias_host(host)
    if any(normalized_host == suffix or normalized_host.endswith(f".{suffix}") for suffix in COMMON_ALIAS_CITATION_HOST_SUFFIXES):
        return False
    compact_name = _compact_alias_token(canonical_name)
    compact_host = _compact_alias_token(normalized_host)
    if len(compact_name) >= 4 and compact_name in compact_host:
        return True
    terms = _alias_terms(canonical_name)
    return len(terms) >= 2 and all(term in compact_host for term in terms)


def _append_alias_candidate(
    candidates: list[dict[str, Any]],
    seen: set[str],
    *,
    entity: dict[str, Any],
    alias: str,
    alias_type: str,
    source: str,
    confidence: float,
    reason: str | None = None,
    evidence_answer_run_ids: tuple[str, ...] = (),
    evidence_urls: tuple[str, ...] = (),
    evidence_count: int | None = None,
) -> None:
    normalized_alias = alias.strip()
    key = normalized_alias.lower()
    if not normalized_alias:
        return
    if key in seen:
        for candidate in candidates:
            if str(candidate.get("alias", "")).lower() != key:
                continue
            if evidence_answer_run_ids:
                existing_ids = list(candidate.get("evidence_answer_run_ids") or [])
                for answer_run_id in evidence_answer_run_ids:
                    if answer_run_id not in existing_ids:
                        existing_ids.append(answer_run_id)
                candidate["evidence_answer_run_ids"] = existing_ids[:5]
            if evidence_urls:
                existing_urls = list(candidate.get("evidence_urls") or [])
                for evidence_url in evidence_urls:
                    if evidence_url not in existing_urls:
                        existing_urls.append(evidence_url)
                candidate["evidence_urls"] = existing_urls[:5]
            if evidence_count is not None:
                candidate["evidence_count"] = int(candidate.get("evidence_count") or 0) + evidence_count
            supporting_sources = list(candidate.get("supporting_sources") or [])
            if source not in supporting_sources:
                supporting_sources.append(source)
            candidate["supporting_sources"] = supporting_sources
            if reason and source.startswith("evidence_"):
                candidate["reason"] = f"{candidate['reason']}; {reason}"
            return
        return
    seen.add(key)
    candidate = {
        "id": _stable_id(
            "entity-alias-candidate",
            entity["entity_kind"],
            entity["id"],
            normalized_alias,
            alias_type,
            source,
        ),
        "entity_id": str(entity["id"]),
        "entity_kind": str(entity["entity_kind"]),
        "alias": normalized_alias,
        "alias_type": alias_type,
        "source": source,
        "confidence": confidence,
        "reason": reason or f"candidate from {source}",
    }
    if evidence_answer_run_ids:
        candidate["evidence_answer_run_ids"] = list(evidence_answer_run_ids)
    if evidence_urls:
        candidate["evidence_urls"] = list(evidence_urls)
    if evidence_count is not None:
        candidate["evidence_count"] = evidence_count
    candidates.append(candidate)


def _artifact_hash(content: str | bytes) -> str:
    payload = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(payload).hexdigest()


def _parse_prompt_import_csv(
    *,
    project_id: str,
    csv_content: str,
    max_rows: int,
) -> tuple[dict[str, Any], ...]:
    content = csv_content.strip()
    if not content:
        raise ValueError("csv_content is required")
    reader = csv.DictReader(StringIO(content))
    if not reader.fieldnames:
        raise ValueError("csv header is required")
    fieldnames = {field.strip() for field in reader.fieldnames if field}
    missing = sorted({"text", "intent_type"} - fieldnames)
    if missing:
        raise ValueError(f"csv missing required columns: {', '.join(missing)}")
    prompts: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    for row_index, row in enumerate(reader, start=1):
        if row_index > max_rows:
            raise ValueError(f"csv row count exceeds max_rows={max_rows}")
        prompt = {str(key).strip(): (value.strip() if isinstance(value, str) else value) for key, value in row.items() if key}
        text = str(prompt.get("text") or "").strip()
        intent_type = str(prompt.get("intent_type") or "").strip()
        if not text:
            raise ValueError(f"row {row_index} text is required")
        if not intent_type:
            raise ValueError(f"row {row_index} intent_type is required")
        normalized_key = text.lower()
        if normalized_key in seen_texts:
            raise ValueError(f"row {row_index} duplicates prompt text")
        seen_texts.add(normalized_key)
        prompt["project_id"] = project_id
        prompt["text"] = text
        prompt["intent_type"] = intent_type
        prompts.append(prompt)
    if not prompts:
        raise ValueError("csv must contain at least one prompt row")
    return tuple(prompts)


def _parse_knowledge_fact_import_csv(
    *,
    project_id: str,
    csv_content: str,
    max_rows: int,
    default_market_code: str,
) -> tuple[dict[str, Any], ...]:
    content = csv_content.strip()
    if not content:
        raise ValueError("csv_content is required")
    reader = csv.DictReader(StringIO(content))
    if not reader.fieldnames:
        raise ValueError("csv header is required")
    fieldnames = {field.strip() for field in reader.fieldnames if field}
    missing = sorted({"fact_type", "subject", "predicate", "object_value"} - fieldnames)
    if missing:
        raise ValueError(f"csv missing required columns: {', '.join(missing)}")
    facts: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str, str, str, str]] = set()
    for row_index, row in enumerate(reader, start=1):
        if row_index > max_rows:
            raise ValueError(f"csv row count exceeds max_rows={max_rows}")
        fact = {str(key).strip(): (value.strip() if isinstance(value, str) else value) for key, value in row.items() if key}
        fact_type = str(fact.get("fact_type") or "").strip()
        subject = str(fact.get("subject") or "").strip()
        predicate = str(fact.get("predicate") or "").strip()
        object_value = str(fact.get("object_value") or "").strip()
        if not fact_type:
            raise ValueError(f"row {row_index} fact_type is required")
        if not subject:
            raise ValueError(f"row {row_index} subject is required")
        if not predicate:
            raise ValueError(f"row {row_index} predicate is required")
        if not object_value:
            raise ValueError(f"row {row_index} object_value is required")
        market_code = str(fact.get("market_code") or default_market_code or "AU").strip().upper()
        city = str(fact.get("city") or "").strip()
        normalized_key = (
            market_code,
            fact_type.lower(),
            subject.lower(),
            predicate.lower(),
            object_value.lower(),
            city.lower(),
        )
        if normalized_key in seen_keys:
            raise ValueError(f"row {row_index} duplicates knowledge fact")
        seen_keys.add(normalized_key)
        try:
            confidence = float(str(fact.get("confidence") or "0.8").strip())
        except ValueError as exc:
            raise ValueError(f"row {row_index} confidence must be a number") from exc
        if confidence < 0 or confidence > 1:
            raise ValueError(f"row {row_index} confidence must be between 0 and 1")
        fact["project_id"] = project_id
        fact["market_code"] = market_code
        fact["fact_type"] = fact_type
        fact["subject"] = subject
        fact["predicate"] = predicate
        fact["object_value"] = object_value
        fact["city"] = city or None
        fact["confidence"] = confidence
        fact["status"] = str(fact.get("status") or KNOWLEDGE_FACT_APPROVED_STATUS).strip() or KNOWLEDGE_FACT_APPROVED_STATUS
        facts.append(fact)
    if not facts:
        raise ValueError("csv must contain at least one knowledge fact row")
    return tuple(facts)


def _normalize_import_prompt(
    *,
    prompt: dict[str, Any],
    project: dict[str, Any],
    default_competitors: tuple[str, ...],
) -> dict[str, Any]:
    def text_value(key: str, default: str) -> str:
        value = str(prompt.get(key) or "").strip()
        return value or default

    def int_value(key: str, default: int) -> int:
        raw = str(prompt.get(key) or "").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{key} must be an integer") from exc
        if value < 0:
            raise ValueError(f"{key} must be >= 0")
        return value

    def float_value(key: str, default: float) -> float:
        raw = str(prompt.get(key) or "").strip()
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"{key} must be a number") from exc
        if value < 0 or value > 1:
            raise ValueError(f"{key} must be between 0 and 1")
        return value

    competitors_raw = str(prompt.get("competitors") or "").strip()
    competitors = (
        tuple(item.strip() for item in competitors_raw.replace("|", ";").split(";") if item.strip())
        if competitors_raw
        else default_competitors
    )
    if len(competitors) > 5:
        raise ValueError("competitors must contain at most 5 items")
    return {
        "project_id": str(project["id"]),
        "market_code": text_value("market_code", str(project["market_code"])),
        "industry_code": text_value("industry_code", str(project["industry_code"])),
        "text": str(prompt["text"]),
        "intent_type": str(prompt["intent_type"]),
        "city": text_value("city", "Australia"),
        "language": text_value("language", "en-AU"),
        "target_brand": text_value("target_brand", str(project["target_brand"])),
        "competitors": competitors,
        "priority": int_value("priority", 0),
        "intent_weight": float_value("intent_weight", 1.0),
        "prompt_version": text_value("prompt_version", str(project["prompt_version"])),
        "status": text_value("status", "active"),
    }


def _render_runtime_report_markdown(report: RuntimeReportExport) -> str:
    report_export = report.report_export
    snapshot = report.score_snapshots[0] if report.score_snapshots else {}
    graph = report.citation_graph
    method_disclosure = _runtime_method_disclosure(report)
    lines = [
        "# GENO AU Evidence Report",
        "",
        f"- Report version: {report_export['report_version']}",
        f"- Market: {report_export['market_code']}",
        f"- Sample size: {report_export['sample_size']}",
        f"- Prompt version: {report_export['prompt_version']}",
        f"- Formula: {report_export['scoring_formula_version']}",
        f"- Methodology hash: {report_export['methodology_hash']}",
        f"- Window: {report_export['window_start']} to {report_export['window_end']}",
        "",
        "## Score Snapshot",
        "",
        f"- Final score: {snapshot.get('final_score', 'n/a')}",
        f"- Trigger rate: {snapshot.get('trigger_rate', 'n/a')}",
        f"- Mention rate: {snapshot.get('mention_rate', 'n/a')}",
        f"- Recommendation rate: {snapshot.get('recommendation_rate', 'n/a')}",
        f"- Dispersion: {snapshot.get('dispersion', 'n/a')}",
        "",
        "## Method Disclosure",
        "",
        *render_methodology_disclosure_lines(method_disclosure),
        "",
        "## Audit Summary",
        "",
        *render_audit_summary_lines(method_disclosure.get("audit_summary")),
        "",
        "## Evidence Appendix",
        "",
    ]
    for answer_run in report.answer_runs:
        lines.append(
            f"- {answer_run['platform']} / {answer_run['surface']} / {answer_run['city']}: "
            f"{answer_run.get('prompt_text') or answer_run['prompt_question_id']} "
            f"(answer_run_id={answer_run['id']})"
        )
    lines.extend(["", "## Citation Graph", ""])
    if graph:
        lines.append(f"- Source nodes: {len(graph.nodes)}")
        lines.append(f"- Evidence links: {len(graph.evidence_links)}")
        lines.append(f"- Source gaps: {len(graph.source_gaps)}")
        lines.append(f"- Competitor benchmarks: {len(graph.competitor_benchmarks)}")
        lines.extend(["", "### Source Gaps", ""])
        for gap in graph.source_gaps:
            lines.append(f"- {gap['source_type']}: {gap['gap_type']}; {gap['recommendation']}")
    else:
        lines.append("- No citation graph stored for this report.")
    lines.extend(["", "## Audit Events", ""])
    for event in report.audit_events:
        lines.append(
            f"- {event['event_type']} target={event['target_type']} "
            f"method={event.get('method_version') or 'n/a'}"
        )
    lines.extend(["", "## Traceability", ""])
    lines.append(
        "This artifact is regenerated from frozen runtime data: "
        "ReportExport -> VisibilityScoreSnapshot -> ReportEvidence/AnswerRun -> CitationGraph -> AuditEvent."
    )
    return "\n".join(lines) + "\n"


def _render_white_label_report_markdown(
    report: RuntimeReportExport,
    *,
    client_name: str,
    prepared_by: str,
    logo_url: str | None = None,
    primary_color: str | None = None,
    secondary_color: str | None = None,
    footer_text: str | None = None,
) -> str:
    report_export = report.report_export
    snapshot = report.score_snapshots[0] if report.score_snapshots else {}
    graph = report.citation_graph
    method_disclosure = _runtime_method_disclosure(report)
    platform_values = sorted(
        {
            str(answer_run.get("platform"))
            for answer_run in report.answer_runs
            if answer_run.get("platform")
        }
    )
    city_values = sorted(
        {
            str(answer_run.get("city"))
            for answer_run in report.answer_runs
            if answer_run.get("city")
        }
    )
    lines = [
        f"# {client_name} GEO Evidence Report",
        "",
        f"Prepared by: {prepared_by}",
        f"Market: {report_export.get('market_code', 'unknown')}",
        f"Report version: {report_export.get('report_version', 'unknown')}",
        f"Exported at: {report_export.get('exported_at', 'unknown')}",
        f"Methodology hash: {report_export.get('methodology_hash', 'unknown')}",
        f"Logo URL: {logo_url or 'not configured'}",
        f"Theme colors: {primary_color or 'default'} / {secondary_color or 'default'}",
        "",
        "## Executive Snapshot",
        "",
        f"- Final score: {snapshot.get('final_score', 'n/a')}",
        f"- Trigger rate: {snapshot.get('trigger_rate', 'n/a')}",
        f"- Mention rate: {snapshot.get('mention_rate', 'n/a')}",
        f"- Recommendation rate: {snapshot.get('recommendation_rate', 'n/a')}",
        f"- Evidence rows in this artifact: {len(report.answer_runs)}",
        f"- Platforms: {', '.join(platform_values) if platform_values else 'unknown'}",
        f"- Cities: {', '.join(city_values) if city_values else 'unknown'}",
        "",
        "## Client-Ready Method Notes",
        "",
        "- This white-label PDF is regenerated from the frozen runtime ReportExport snapshot.",
        "- Active appendix filters affect only this downloadable artifact, not stored score snapshots or evidence ids.",
        "- Every displayed score remains traceable to answer runs, citations, score contributions, and audit events.",
        f"- Google coverage: {method_disclosure['google_coverage']}",
        f"- API-vs-browser fidelity: {method_disclosure['api_browser_fidelity']['status']}",
        *render_methodology_disclosure_lines(method_disclosure),
        "",
        "## Evidence Highlights",
        "",
    ]
    for answer_run in report.answer_runs[:12]:
        lines.append(
            f"- {answer_run.get('platform', 'platform')} / {answer_run.get('city', 'city')}: "
            f"{answer_run.get('prompt_text') or answer_run.get('prompt_question_id') or answer_run.get('id')} "
            f"(run={answer_run.get('id')})"
        )
    if not report.answer_runs:
        lines.append("- No evidence rows match the selected filters.")
    lines.extend(["", "## Source & Audit Summary", ""])
    if graph:
        lines.append(f"- Source nodes: {len(graph.nodes)}")
        lines.append(f"- Evidence links: {len(graph.evidence_links)}")
        lines.append(f"- Source gaps: {len(graph.source_gaps)}")
        lines.append(f"- Competitor benchmarks: {len(graph.competitor_benchmarks)}")
    else:
        lines.append("- No citation graph stored for this report.")
    lines.extend(render_audit_summary_lines(method_disclosure.get("audit_summary")))
    lines.append(f"- Report audit events: {len(report.audit_events)}")
    for event in report.audit_events[:5]:
        lines.append(
            f"- Audit: {event.get('event_type', 'audit_event')} "
            f"target={event.get('target_type', 'target')} "
            f"method={event.get('method_version') or 'n/a'}"
        )
    lines.extend(["", "## Footer", ""])
    if footer_text:
        lines.append(footer_text)
        lines.append("")
    lines.append(
        f"{prepared_by} white-label template `white_label_v1`; "
        f"ReportExport {report_export.get('id', 'unknown')} remains the source of truth."
    )
    return "\n".join(lines) + "\n"


def _render_runtime_report_csv(report: RuntimeReportExport) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "report_export_id",
            "report_version",
            "answer_run_id",
            "prompt_question_id",
            "prompt_text",
            "prompt_intent_type",
            "platform",
            "surface",
            "city",
            "access_method",
            "sample_index",
            "sample_size",
            "answer_present",
            "surface_triggered",
            "status",
            "total_cost",
            "citation_count",
            "audit_event_count",
        ],
    )
    writer.writeheader()
    for answer_run in report.answer_runs:
        writer.writerow(
            {
                "report_export_id": report.report_export["id"],
                "report_version": report.report_export["report_version"],
                "answer_run_id": answer_run["id"],
                "prompt_question_id": answer_run["prompt_question_id"],
                "prompt_text": answer_run.get("prompt_text") or "",
                "prompt_intent_type": answer_run.get("prompt_intent_type") or "",
                "platform": answer_run["platform"],
                "surface": answer_run["surface"],
                "city": answer_run["city"],
                "access_method": answer_run["access_method"],
                "sample_index": answer_run["sample_index"],
                "sample_size": answer_run["sample_size"],
                "answer_present": answer_run["answer_present"],
                "surface_triggered": answer_run["surface_triggered"],
                "status": answer_run["status"],
                "total_cost": answer_run.get("total_cost") or "",
                "citation_count": answer_run.get("citation_count") or "",
                "audit_event_count": answer_run.get("audit_event_count") or "",
            }
        )
    return output.getvalue()


def _filter_runtime_report_answer_runs(
    answer_runs: tuple[dict[str, Any], ...],
    *,
    platform: str | None = None,
    city: str | None = None,
    intent_type: str | None = None,
    status: str | None = None,
    sort: str | None = None,
) -> tuple[tuple[dict[str, Any], ...], str]:
    filtered = [
        answer_run
        for answer_run in answer_runs
        if (not platform or answer_run.get("platform") == platform)
        and (not city or answer_run.get("city") == city)
        and (not intent_type or answer_run.get("prompt_intent_type") == intent_type)
        and (not status or answer_run.get("status") == status)
    ]
    if sort is None:
        return tuple(filtered), "report_evidence_order"
    sort_key, _ = _runtime_evidence_sort(sort)

    def sort_value(answer_run: dict[str, Any]) -> tuple[object, ...]:
        if sort_key == "collected_at_asc":
            return (answer_run.get("collected_at") or "", answer_run.get("id") or "")
        if sort_key == "cost_desc":
            return (-(float(answer_run.get("total_cost") or 0)), answer_run.get("collected_at") or "", answer_run.get("id") or "")
        if sort_key == "cost_asc":
            return (float(answer_run.get("total_cost") or 0), answer_run.get("collected_at") or "", answer_run.get("id") or "")
        if sort_key == "citation_count_desc":
            return (-(int(answer_run.get("citation_count") or 0)), answer_run.get("collected_at") or "", answer_run.get("id") or "")
        if sort_key == "audit_count_desc":
            return (-(int(answer_run.get("audit_event_count") or 0)), answer_run.get("collected_at") or "", answer_run.get("id") or "")
        return (answer_run.get("collected_at") or "", answer_run.get("id") or "")

    if sort_key == "collected_at_desc":
        filtered.sort(key=lambda item: (item.get("collected_at") or "", item.get("id") or ""), reverse=True)
    else:
        filtered.sort(key=sort_value)
    return tuple(filtered), sort_key


def _render_runtime_evidence_csv(page: RuntimeEvidencePage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "answer_run_id",
            "project_id",
            "prompt_question_id",
            "prompt_text",
            "prompt_intent_type",
            "prompt_version",
            "platform",
            "surface",
            "access_method",
            "market_code",
            "city",
            "language",
            "device",
            "sample_index",
            "sample_size",
            "answer_present",
            "surface_triggered",
            "status",
            "collector_backend_id",
            "collector_version",
            "raw_payload_hash",
            "citation_count",
            "asset_count",
            "audit_event_count",
            "total_cost",
        ],
    )
    writer.writeheader()
    for record in page.records:
        answer_run = record.answer_run
        writer.writerow(
            {
                "answer_run_id": answer_run["id"],
                "project_id": answer_run.get("project_id") or "",
                "prompt_question_id": answer_run.get("prompt_question_id") or "",
                "prompt_text": answer_run.get("prompt_text") or "",
                "prompt_intent_type": answer_run.get("prompt_intent_type") or "",
                "prompt_version": answer_run.get("prompt_version") or "",
                "platform": answer_run.get("platform") or "",
                "surface": answer_run.get("surface") or "",
                "access_method": answer_run.get("access_method") or "",
                "market_code": answer_run.get("market_code") or "",
                "city": answer_run.get("city") or "",
                "language": answer_run.get("language") or "",
                "device": answer_run.get("device") or "",
                "sample_index": answer_run.get("sample_index") or "",
                "sample_size": answer_run.get("sample_size") or "",
                "answer_present": answer_run.get("answer_present"),
                "surface_triggered": answer_run.get("surface_triggered"),
                "status": answer_run.get("status") or "",
                "collector_backend_id": answer_run.get("collector_backend_id") or "",
                "collector_version": answer_run.get("collector_version") or "",
                "raw_payload_hash": (record.raw_answer or {}).get("raw_payload_hash", ""),
                "citation_count": len(record.citations),
                "asset_count": len(record.evidence_assets),
                "audit_event_count": len(record.audit_events),
                "total_cost": (record.collection_cost or {}).get("total_cost", ""),
            }
        )
    return output.getvalue()


def _render_runtime_collection_runs_csv(page: RuntimeCollectionRunPage) -> str:
    def dict_keys(value: object) -> str:
        if not isinstance(value, dict):
            return ""
        return _pipe_join(sorted(str(key) for key in value))

    def dict_counts(value: object) -> str:
        if not isinstance(value, dict):
            return ""
        return _pipe_join([f"{key}={value[key]}" for key in sorted(value)])

    def dict_hash(value: object) -> str:
        payload = value if isinstance(value, dict) else {}
        return _artifact_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True))

    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "collection_run_id",
            "project_id",
            "run_type",
            "mode",
            "planned_runs",
            "attempted_runs",
            "success_count",
            "failure_count",
            "success_rate",
            "trigger_rate",
            "answer_present_rate",
            "total_cost",
            "average_cost_per_run",
            "total_duration_ms",
            "average_duration_ms",
            "collector_backend_ids",
            "platform_distribution_keys",
            "platform_distribution_counts",
            "city_distribution_keys",
            "city_distribution_counts",
            "access_method_distribution_keys",
            "access_method_distribution_counts",
            "failure_summary_key_count",
            "failure_summary_hash",
            "answer_run_count",
            "answer_run_ids",
            "started_at",
            "completed_at",
            "created_at",
            "audit_event_count",
            "latest_audit_event_type",
            "latest_audit_method_version",
            "latest_audit_after_hash",
        ],
    )
    writer.writeheader()
    for record in page.records:
        collection_run = record.collection_run
        latest_audit_event = _latest_audit_event(record.audit_events)
        failure_summary = collection_run.get("failure_summary") if isinstance(collection_run.get("failure_summary"), dict) else {}
        answer_run_ids = collection_run.get("answer_run_ids")
        if not isinstance(answer_run_ids, (list, tuple)):
            answer_run_ids = ()
        writer.writerow(
            {
                "collection_run_id": collection_run.get("id") or "",
                "project_id": collection_run.get("project_id") or "",
                "run_type": collection_run.get("run_type") or "",
                "mode": collection_run.get("mode") or "",
                "planned_runs": collection_run.get("planned_runs") or 0,
                "attempted_runs": collection_run.get("attempted_runs") or 0,
                "success_count": collection_run.get("success_count") or 0,
                "failure_count": collection_run.get("failure_count") or 0,
                "success_rate": collection_run.get("success_rate") or 0,
                "trigger_rate": collection_run.get("trigger_rate") or 0,
                "answer_present_rate": collection_run.get("answer_present_rate") or 0,
                "total_cost": collection_run.get("total_cost") or 0,
                "average_cost_per_run": collection_run.get("average_cost_per_run") or 0,
                "total_duration_ms": collection_run.get("total_duration_ms") or 0,
                "average_duration_ms": collection_run.get("average_duration_ms") or 0,
                "collector_backend_ids": _pipe_join(collection_run.get("collector_backend_ids")),
                "platform_distribution_keys": dict_keys(collection_run.get("platform_distribution")),
                "platform_distribution_counts": dict_counts(collection_run.get("platform_distribution")),
                "city_distribution_keys": dict_keys(collection_run.get("city_distribution")),
                "city_distribution_counts": dict_counts(collection_run.get("city_distribution")),
                "access_method_distribution_keys": dict_keys(collection_run.get("access_method_distribution")),
                "access_method_distribution_counts": dict_counts(collection_run.get("access_method_distribution")),
                "failure_summary_key_count": len(failure_summary),
                "failure_summary_hash": dict_hash(failure_summary),
                "answer_run_count": len(answer_run_ids),
                "answer_run_ids": _pipe_join(answer_run_ids),
                "started_at": collection_run.get("started_at") or "",
                "completed_at": collection_run.get("completed_at") or "",
                "created_at": collection_run.get("created_at") or "",
                "audit_event_count": len(record.audit_events),
                "latest_audit_event_type": latest_audit_event.get("event_type") or "",
                "latest_audit_method_version": latest_audit_event.get("method_version") or "",
                "latest_audit_after_hash": latest_audit_event.get("after_hash") or "",
            }
        )
    return output.getvalue()


def _render_runtime_fidelity_checks_csv(page: RuntimeFidelityCheckPage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "fidelity_check_id",
            "project_id",
            "report_export_id",
            "status",
            "official_api_records",
            "browser_records",
            "comparable_prompt_city_pairs",
            "mismatch_count",
            "difference_rate",
            "payload_hash",
            "payload_key_count",
            "payload_keys",
            "answer_run_count",
            "answer_run_ids",
            "checked_by_hash",
            "checked_at",
            "audit_event_count",
            "latest_audit_event_type",
            "latest_audit_method_version",
            "latest_audit_after_hash",
        ],
    )
    writer.writeheader()
    for record in page.records:
        fidelity_check = record.fidelity_check
        latest_audit_event = _latest_audit_event(record.audit_events)
        payload = fidelity_check.get("payload") if isinstance(fidelity_check.get("payload"), dict) else {}
        answer_run_ids = fidelity_check.get("answer_run_ids")
        if not isinstance(answer_run_ids, (list, tuple)):
            answer_run_ids = ()
        writer.writerow(
            {
                "fidelity_check_id": fidelity_check.get("id") or "",
                "project_id": fidelity_check.get("project_id") or "",
                "report_export_id": fidelity_check.get("report_export_id") or "",
                "status": fidelity_check.get("status") or "",
                "official_api_records": fidelity_check.get("official_api_records") or 0,
                "browser_records": fidelity_check.get("browser_records") or 0,
                "comparable_prompt_city_pairs": fidelity_check.get("comparable_prompt_city_pairs") or 0,
                "mismatch_count": fidelity_check.get("mismatch_count") or 0,
                "difference_rate": fidelity_check.get("difference_rate") if fidelity_check.get("difference_rate") is not None else "",
                "payload_hash": fidelity_check.get("payload_hash") or "",
                "payload_key_count": len(payload),
                "payload_keys": _pipe_join(sorted(str(key) for key in payload)),
                "answer_run_count": len(answer_run_ids),
                "answer_run_ids": _pipe_join(answer_run_ids),
                "checked_by_hash": _hash_text_field(fidelity_check.get("checked_by")),
                "checked_at": fidelity_check.get("checked_at") or "",
                "audit_event_count": len(record.audit_events),
                "latest_audit_event_type": latest_audit_event.get("event_type") or "",
                "latest_audit_method_version": latest_audit_event.get("method_version") or "",
                "latest_audit_after_hash": latest_audit_event.get("after_hash") or "",
            }
        )
    return output.getvalue()


def _render_runtime_prompts_csv(page: RuntimePromptPage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "prompt_question_id",
            "project_id",
            "market_code",
            "industry_code",
            "prompt_text_hash",
            "intent_type",
            "city",
            "language",
            "target_brand_hash",
            "competitor_count",
            "competitor_name_hashes",
            "priority",
            "intent_weight",
            "prompt_version",
            "status",
        ],
    )
    writer.writeheader()
    for prompt in page.records:
        competitors = prompt.get("competitors")
        if not isinstance(competitors, (list, tuple)):
            competitors = ()
        writer.writerow(
            {
                "prompt_question_id": prompt.get("id") or "",
                "project_id": prompt.get("project_id") or "",
                "market_code": prompt.get("market_code") or "",
                "industry_code": prompt.get("industry_code") or "",
                "prompt_text_hash": _hash_text_field(prompt.get("text")),
                "intent_type": prompt.get("intent_type") or "",
                "city": prompt.get("city") or "",
                "language": prompt.get("language") or "",
                "target_brand_hash": _hash_text_field(prompt.get("target_brand")),
                "competitor_count": len(competitors),
                "competitor_name_hashes": _pipe_join([_hash_text_field(competitor) for competitor in competitors]),
                "priority": prompt.get("priority") or 0,
                "intent_weight": prompt.get("intent_weight") or 0,
                "prompt_version": prompt.get("prompt_version") or "",
                "status": prompt.get("status") or "",
            }
        )
    return output.getvalue()


def _render_runtime_project_lifecycle_events_csv(page: RuntimeProjectLifecycleEventPage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "audit_event_id",
            "project_id",
            "event_type",
            "actor_type",
            "actor_id",
            "target_id",
            "reason",
            "method_version",
            "action",
            "status_before",
            "status_after",
            "changed_fields",
            "before_hash",
            "after_hash",
            "created_at",
        ],
    )
    writer.writeheader()
    for record in page.records:
        lifecycle_event = record.lifecycle_event
        changed_fields = lifecycle_event.get("changed_fields") or []
        writer.writerow(
            {
                "audit_event_id": lifecycle_event.get("id") or "",
                "project_id": lifecycle_event.get("project_id") or "",
                "event_type": lifecycle_event.get("event_type") or "",
                "actor_type": lifecycle_event.get("actor_type") or "",
                "actor_id": lifecycle_event.get("actor_id") or "",
                "target_id": lifecycle_event.get("target_id") or "",
                "reason": lifecycle_event.get("reason") or "",
                "method_version": lifecycle_event.get("method_version") or "",
                "action": lifecycle_event.get("action") or "",
                "status_before": lifecycle_event.get("status_before") or "",
                "status_after": lifecycle_event.get("status_after") or "",
                "changed_fields": "|".join(str(field) for field in changed_fields),
                "before_hash": lifecycle_event.get("before_hash") or "",
                "after_hash": lifecycle_event.get("after_hash") or "",
                "created_at": lifecycle_event.get("created_at") or "",
            }
        )
    return output.getvalue()


def _render_runtime_audit_events_csv(page: RuntimeAuditEventPage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "audit_event_id",
            "project_id",
            "event_type",
            "actor_type",
            "actor_id",
            "target_type",
            "target_id",
            "method_version",
            "reason",
            "before_hash",
            "after_hash",
            "input_ref_keys",
            "output_ref_keys",
            "created_at",
        ],
    )
    writer.writeheader()
    for record in page.records:
        audit_event = record.audit_event
        input_refs = audit_event.get("input_refs") if isinstance(audit_event.get("input_refs"), dict) else {}
        output_refs = audit_event.get("output_refs") if isinstance(audit_event.get("output_refs"), dict) else {}
        writer.writerow(
            {
                "audit_event_id": audit_event.get("id") or "",
                "project_id": audit_event.get("project_id") or "",
                "event_type": audit_event.get("event_type") or "",
                "actor_type": audit_event.get("actor_type") or "",
                "actor_id": audit_event.get("actor_id") or "",
                "target_type": audit_event.get("target_type") or "",
                "target_id": audit_event.get("target_id") or "",
                "method_version": audit_event.get("method_version") or "",
                "reason": audit_event.get("reason") or "",
                "before_hash": audit_event.get("before_hash") or "",
                "after_hash": audit_event.get("after_hash") or "",
                "input_ref_keys": "|".join(sorted(str(key) for key in input_refs.keys())),
                "output_ref_keys": "|".join(sorted(str(key) for key in output_refs.keys())),
                "created_at": audit_event.get("created_at") or "",
            }
        )
    return output.getvalue()


def _render_runtime_notification_email_suppressions_csv(page: RuntimeNotificationEmailSuppressionPage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "suppression_id",
            "project_id",
            "recipient_hash",
            "status",
            "source",
            "source_ref",
            "created_by",
            "created_at",
            "updated_by",
            "updated_at",
            "feedback_event_id",
            "delivery_id",
            "notification_id",
            "subscription_id",
            "feedback_type",
            "provider",
            "provider_event_id_hash",
            "metadata_keys",
            "audit_event_count",
            "latest_audit_event_type",
            "latest_audit_method_version",
            "latest_audit_after_hash",
        ],
    )
    writer.writeheader()
    for record in page.records:
        suppression = record.suppression
        metadata = suppression.get("metadata") if isinstance(suppression.get("metadata"), dict) else {}
        latest_audit_event = record.audit_events[0] if record.audit_events else {}
        writer.writerow(
            {
                "suppression_id": suppression.get("id") or "",
                "project_id": suppression.get("project_id") or "",
                "recipient_hash": suppression.get("recipient_hash") or "",
                "status": suppression.get("status") or "",
                "source": suppression.get("source") or "",
                "source_ref": suppression.get("source_ref") or "",
                "created_by": suppression.get("created_by") or "",
                "created_at": suppression.get("created_at") or "",
                "updated_by": suppression.get("updated_by") or "",
                "updated_at": suppression.get("updated_at") or "",
                "feedback_event_id": metadata.get("feedback_event_id") or "",
                "delivery_id": metadata.get("delivery_id") or "",
                "notification_id": metadata.get("notification_id") or "",
                "subscription_id": metadata.get("subscription_id") or "",
                "feedback_type": metadata.get("feedback_type") or "",
                "provider": metadata.get("provider") or "",
                "provider_event_id_hash": metadata.get("provider_event_id_hash") or "",
                "metadata_keys": "|".join(sorted(str(key) for key in metadata)),
                "audit_event_count": len(record.audit_events),
                "latest_audit_event_type": latest_audit_event.get("event_type") or "",
                "latest_audit_method_version": latest_audit_event.get("method_version") or "",
                "latest_audit_after_hash": latest_audit_event.get("after_hash") or "",
            }
        )
    return output.getvalue()


def _render_runtime_notification_deliveries_csv(page: RuntimeNotificationDeliveryPage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "delivery_id",
            "project_id",
            "notification_id",
            "subscription_id",
            "channel",
            "endpoint_url_hash",
            "status",
            "attempt_count",
            "max_attempts",
            "lease_expires_at",
            "next_attempt_at",
            "response_status",
            "response_body_hash",
            "error_message_hash",
            "created_at",
            "updated_by",
            "updated_at",
            "notification_type",
            "notification_severity",
            "notification_status",
            "notification_target_type",
            "notification_target_id",
            "subscription_status",
            "subscription_severity_threshold",
            "payload_version",
            "payload_keys",
            "payload_metadata_keys",
            "audit_event_count",
            "latest_audit_event_type",
            "latest_audit_method_version",
            "latest_audit_after_hash",
        ],
    )
    writer.writeheader()
    for record in page.records:
        delivery = record.delivery
        notification = record.notification or {}
        subscription = record.subscription or {}
        payload = delivery.get("payload") if isinstance(delivery.get("payload"), dict) else {}
        payload_metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        latest_audit_event = record.audit_events[0] if record.audit_events else {}
        endpoint_url = str(delivery.get("endpoint_url") or "")
        error_message = str(delivery.get("error_message") or "")
        writer.writerow(
            {
                "delivery_id": delivery.get("id") or "",
                "project_id": delivery.get("project_id") or "",
                "notification_id": delivery.get("notification_id") or "",
                "subscription_id": delivery.get("subscription_id") or "",
                "channel": delivery.get("channel") or "",
                "endpoint_url_hash": _artifact_hash(endpoint_url) if endpoint_url else "",
                "status": delivery.get("status") or "",
                "attempt_count": delivery.get("attempt_count") or 0,
                "max_attempts": delivery.get("max_attempts") or 0,
                "lease_expires_at": delivery.get("lease_expires_at") or "",
                "next_attempt_at": delivery.get("next_attempt_at") or "",
                "response_status": delivery.get("response_status") or "",
                "response_body_hash": delivery.get("response_body_hash") or "",
                "error_message_hash": _artifact_hash(error_message) if error_message else "",
                "created_at": delivery.get("created_at") or "",
                "updated_by": delivery.get("updated_by") or "",
                "updated_at": delivery.get("updated_at") or "",
                "notification_type": notification.get("notification_type") or "",
                "notification_severity": notification.get("severity") or "",
                "notification_status": notification.get("status") or "",
                "notification_target_type": notification.get("target_type") or "",
                "notification_target_id": notification.get("target_id") or "",
                "subscription_status": subscription.get("status") or "",
                "subscription_severity_threshold": subscription.get("severity_threshold") or "",
                "payload_version": payload.get("delivery_version") or "",
                "payload_keys": "|".join(sorted(str(key) for key in payload)),
                "payload_metadata_keys": "|".join(sorted(str(key) for key in payload_metadata)),
                "audit_event_count": len(record.audit_events),
                "latest_audit_event_type": latest_audit_event.get("event_type") or "",
                "latest_audit_method_version": latest_audit_event.get("method_version") or "",
                "latest_audit_after_hash": latest_audit_event.get("after_hash") or "",
            }
        )
    return output.getvalue()


def _render_runtime_notification_subscriptions_csv(page: RuntimeNotificationSubscriptionPage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "subscription_id",
            "project_id",
            "channel",
            "endpoint_url_hash",
            "event_types",
            "severity_threshold",
            "status",
            "created_by",
            "created_at",
            "updated_by",
            "updated_at",
            "metadata_keys",
            "email_reply_to_hash",
            "email_unsubscribe_url_hash",
            "email_unsubscribe_mailto_hash",
            "email_preferences_url_hash",
            "email_suppressed_recipient_hash_count",
            "webhook_signing_secret_env_present",
            "webhook_signing_secret_key_id",
            "webhook_previous_signing_secret_env_present",
            "webhook_previous_signing_secret_key_id",
            "slack_channel_configured",
            "audit_event_count",
            "latest_audit_event_type",
            "latest_audit_method_version",
            "latest_audit_after_hash",
        ],
    )
    writer.writeheader()
    for record in page.records:
        subscription = record.subscription
        metadata = subscription.get("metadata") if isinstance(subscription.get("metadata"), dict) else {}
        latest_audit_event = record.audit_events[0] if record.audit_events else {}
        endpoint_url = str(subscription.get("endpoint_url") or "")
        email_reply_to = str(metadata.get("email_reply_to") or "")
        email_unsubscribe_url = str(metadata.get("email_unsubscribe_url") or "")
        email_unsubscribe_mailto = str(metadata.get("email_unsubscribe_mailto") or "")
        email_preferences_url = str(metadata.get("email_preferences_url") or "")
        suppressed_hashes = tuple(
            str(item).strip()
            for item in metadata.get("email_suppressed_recipient_hashes", ())
            if str(item).strip()
        ) if isinstance(metadata.get("email_suppressed_recipient_hashes"), (list, tuple)) else ()
        signing_secret_env = str(metadata.get("signing_secret_env") or metadata.get("webhook_signing_secret_env") or "")
        previous_signing_secret_env = str(
            metadata.get("previous_signing_secret_env") or metadata.get("previous_webhook_signing_secret_env") or ""
        )
        event_types = subscription.get("event_types") if isinstance(subscription.get("event_types"), (list, tuple)) else ()
        writer.writerow(
            {
                "subscription_id": subscription.get("id") or "",
                "project_id": subscription.get("project_id") or "",
                "channel": subscription.get("channel") or "",
                "endpoint_url_hash": _artifact_hash(endpoint_url) if endpoint_url else "",
                "event_types": "|".join(str(event_type) for event_type in event_types),
                "severity_threshold": subscription.get("severity_threshold") or "",
                "status": subscription.get("status") or "",
                "created_by": subscription.get("created_by") or "",
                "created_at": subscription.get("created_at") or "",
                "updated_by": subscription.get("updated_by") or "",
                "updated_at": subscription.get("updated_at") or "",
                "metadata_keys": "|".join(sorted(str(key) for key in metadata)),
                "email_reply_to_hash": runtime_email_body_hash(email_reply_to) if email_reply_to else "",
                "email_unsubscribe_url_hash": _artifact_hash(email_unsubscribe_url) if email_unsubscribe_url else "",
                "email_unsubscribe_mailto_hash": _artifact_hash(email_unsubscribe_mailto) if email_unsubscribe_mailto else "",
                "email_preferences_url_hash": _artifact_hash(email_preferences_url) if email_preferences_url else "",
                "email_suppressed_recipient_hash_count": len(suppressed_hashes),
                "webhook_signing_secret_env_present": bool(signing_secret_env),
                "webhook_signing_secret_key_id": metadata.get("signing_secret_key_id") or "",
                "webhook_previous_signing_secret_env_present": bool(previous_signing_secret_env),
                "webhook_previous_signing_secret_key_id": metadata.get("previous_signing_secret_key_id") or "",
                "slack_channel_configured": bool(str(metadata.get("slack_channel") or "")),
                "audit_event_count": len(record.audit_events),
                "latest_audit_event_type": latest_audit_event.get("event_type") or "",
                "latest_audit_method_version": latest_audit_event.get("method_version") or "",
                "latest_audit_after_hash": latest_audit_event.get("after_hash") or "",
            }
        )
    return output.getvalue()


def _render_runtime_notifications_csv(page: RuntimeNotificationPage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "notification_id",
            "project_id",
            "notification_type",
            "severity",
            "status",
            "target_type",
            "target_id",
            "recipient_role",
            "title_hash",
            "message_hash",
            "payload_keys",
            "payload_status",
            "payload_artifact_type",
            "payload_template",
            "created_by",
            "created_at",
            "read_at",
            "updated_by",
            "updated_at",
            "audit_event_count",
            "latest_audit_event_type",
            "latest_audit_method_version",
            "latest_audit_after_hash",
        ],
    )
    writer.writeheader()
    for record in page.records:
        notification = record.notification
        payload = notification.get("payload") if isinstance(notification.get("payload"), dict) else {}
        latest_audit_event = record.audit_events[0] if record.audit_events else {}
        title = str(notification.get("title") or "")
        message = str(notification.get("message") or "")
        writer.writerow(
            {
                "notification_id": notification.get("id") or "",
                "project_id": notification.get("project_id") or "",
                "notification_type": notification.get("notification_type") or "",
                "severity": notification.get("severity") or "",
                "status": notification.get("status") or "",
                "target_type": notification.get("target_type") or "",
                "target_id": notification.get("target_id") or "",
                "recipient_role": notification.get("recipient_role") or "",
                "title_hash": _artifact_hash(title) if title else "",
                "message_hash": _artifact_hash(message) if message else "",
                "payload_keys": "|".join(sorted(str(key) for key in payload)),
                "payload_status": payload.get("status") or "",
                "payload_artifact_type": payload.get("artifact_type") or "",
                "payload_template": payload.get("template") or "",
                "created_by": notification.get("created_by") or "",
                "created_at": notification.get("created_at") or "",
                "read_at": notification.get("read_at") or "",
                "updated_by": notification.get("updated_by") or "",
                "updated_at": notification.get("updated_at") or "",
                "audit_event_count": len(record.audit_events),
                "latest_audit_event_type": latest_audit_event.get("event_type") or "",
                "latest_audit_method_version": latest_audit_event.get("method_version") or "",
                "latest_audit_after_hash": latest_audit_event.get("after_hash") or "",
            }
        )
    return output.getvalue()


def _render_runtime_report_export_jobs_csv(page: RuntimeReportExportJobPage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "job_id",
            "project_id",
            "report_export_id",
            "status",
            "artifact_type",
            "template",
            "filter_keys",
            "sort",
            "requested_by",
            "requested_at",
            "started_at",
            "completed_at",
            "attempt_count",
            "max_attempts",
            "lease_expires_at",
            "next_attempt_at",
            "artifact_url_hash",
            "error_message_hash",
            "updated_by",
            "updated_at",
            "audit_event_count",
            "latest_audit_event_type",
            "latest_audit_method_version",
            "latest_audit_after_hash",
        ],
    )
    writer.writeheader()
    for record in page.records:
        job = record.report_export_job
        filters = job.get("filters") if isinstance(job.get("filters"), dict) else {}
        latest_audit_event = record.audit_events[0] if record.audit_events else {}
        artifact_url = str(job.get("artifact_url") or "")
        error_message = str(job.get("error_message") or "")
        writer.writerow(
            {
                "job_id": job.get("id") or "",
                "project_id": job.get("project_id") or "",
                "report_export_id": job.get("report_export_id") or "",
                "status": job.get("status") or "",
                "artifact_type": job.get("artifact_type") or "",
                "template": job.get("template") or "",
                "filter_keys": "|".join(sorted(str(key) for key in filters)),
                "sort": job.get("sort") or "",
                "requested_by": job.get("requested_by") or "",
                "requested_at": job.get("requested_at") or "",
                "started_at": job.get("started_at") or "",
                "completed_at": job.get("completed_at") or "",
                "attempt_count": job.get("attempt_count") or 0,
                "max_attempts": job.get("max_attempts") or "",
                "lease_expires_at": job.get("lease_expires_at") or "",
                "next_attempt_at": job.get("next_attempt_at") or "",
                "artifact_url_hash": _artifact_hash(artifact_url) if artifact_url else "",
                "error_message_hash": _artifact_hash(error_message) if error_message else "",
                "updated_by": job.get("updated_by") or "",
                "updated_at": job.get("updated_at") or "",
                "audit_event_count": len(record.audit_events),
                "latest_audit_event_type": latest_audit_event.get("event_type") or "",
                "latest_audit_method_version": latest_audit_event.get("method_version") or "",
                "latest_audit_after_hash": latest_audit_event.get("after_hash") or "",
            }
        )
    return output.getvalue()


def _render_runtime_report_management_events_csv(records: tuple[dict[str, Any], ...]) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "report_export_id",
            "project_id",
            "report_version",
            "report_type",
            "market_code",
            "management_status",
            "management_event_id",
            "management_actor_hash",
            "management_note_hash",
            "management_method_version",
            "management_after_hash",
            "management_created_at",
            "sample_size",
            "scoring_formula_version",
            "methodology_hash",
            "markdown_url_hash",
            "pdf_url_hash",
            "csv_url_hash",
            "exported_at",
        ],
    )
    writer.writeheader()
    for record in records:
        management_event = record.get("management_event")
        actor_id = str(management_event.get("actor_id") or "") if isinstance(management_event, dict) else ""
        note = str(management_event.get("reason") or "") if isinstance(management_event, dict) else ""
        input_refs = management_event.get("input_refs") if isinstance(management_event, dict) else {}
        input_refs = input_refs if isinstance(input_refs, dict) else {}
        status_refs = input_refs.get("status", [])
        management_status = str(status_refs[0]) if status_refs else ""
        markdown_url = str(record.get("markdown_url") or "")
        pdf_url = str(record.get("pdf_url") or "")
        csv_url = str(record.get("csv_url") or "")
        writer.writerow(
            {
                "report_export_id": record.get("id") or "",
                "project_id": record.get("project_id") or "",
                "report_version": record.get("report_version") or "",
                "report_type": record.get("report_type") or "",
                "market_code": record.get("market_code") or "",
                "management_status": management_status,
                "management_event_id": management_event.get("id") if isinstance(management_event, dict) else "",
                "management_actor_hash": _artifact_hash(actor_id) if actor_id else "",
                "management_note_hash": _artifact_hash(note) if note else "",
                "management_method_version": (
                    management_event.get("method_version") if isinstance(management_event, dict) else ""
                ),
                "management_after_hash": management_event.get("after_hash") if isinstance(management_event, dict) else "",
                "management_created_at": management_event.get("created_at") if isinstance(management_event, dict) else "",
                "sample_size": record.get("sample_size") or "",
                "scoring_formula_version": record.get("scoring_formula_version") or "",
                "methodology_hash": record.get("methodology_hash") or "",
                "markdown_url_hash": _artifact_hash(markdown_url) if markdown_url else "",
                "pdf_url_hash": _artifact_hash(pdf_url) if pdf_url else "",
                "csv_url_hash": _artifact_hash(csv_url) if csv_url else "",
                "exported_at": record.get("exported_at") or "",
            }
        )
    return output.getvalue()


def _render_runtime_project_members_csv(page: RuntimeProjectMemberPage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "member_id",
            "project_id",
            "user_id_hash",
            "role",
            "created_at",
            "audit_event_count",
            "latest_audit_event_type",
            "latest_audit_method_version",
            "latest_audit_after_hash",
        ],
    )
    writer.writeheader()
    for record in page.records:
        member = record.member
        latest_audit_event = record.audit_events[0] if record.audit_events else {}
        user_id = str(member.get("user_id") or "")
        writer.writerow(
            {
                "member_id": member.get("id") or "",
                "project_id": member.get("project_id") or "",
                "user_id_hash": _artifact_hash(user_id) if user_id else "",
                "role": member.get("role") or "",
                "created_at": member.get("created_at") or "",
                "audit_event_count": len(record.audit_events),
                "latest_audit_event_type": latest_audit_event.get("event_type") or "",
                "latest_audit_method_version": latest_audit_event.get("method_version") or "",
                "latest_audit_after_hash": latest_audit_event.get("after_hash") or "",
            }
        )
    return output.getvalue()


def _render_runtime_project_member_invitations_csv(page: RuntimeProjectMemberInvitationPage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "invitation_id",
            "project_id",
            "email_hash",
            "role",
            "status",
            "invite_token_hash_present",
            "invited_by_hash",
            "expires_at",
            "accepted_at",
            "revoked_at",
            "created_at",
            "updated_at",
            "audit_event_count",
            "latest_audit_event_type",
            "latest_audit_method_version",
            "latest_audit_after_hash",
        ],
    )
    writer.writeheader()
    for record in page.records:
        invitation = record.invitation
        latest_audit_event = record.audit_events[0] if record.audit_events else {}
        email = str(invitation.get("email") or "")
        invited_by = str(invitation.get("invited_by") or "")
        writer.writerow(
            {
                "invitation_id": invitation.get("id") or "",
                "project_id": invitation.get("project_id") or "",
                "email_hash": _artifact_hash(email) if email else "",
                "role": invitation.get("role") or "",
                "status": invitation.get("status") or "",
                "invite_token_hash_present": bool(invitation.get("invite_token_hash")),
                "invited_by_hash": _artifact_hash(invited_by) if invited_by else "",
                "expires_at": invitation.get("expires_at") or "",
                "accepted_at": invitation.get("accepted_at") or "",
                "revoked_at": invitation.get("revoked_at") or "",
                "created_at": invitation.get("created_at") or "",
                "updated_at": invitation.get("updated_at") or "",
                "audit_event_count": len(record.audit_events),
                "latest_audit_event_type": latest_audit_event.get("event_type") or "",
                "latest_audit_method_version": latest_audit_event.get("method_version") or "",
                "latest_audit_after_hash": latest_audit_event.get("after_hash") or "",
            }
        )
    return output.getvalue()


def _render_runtime_human_reviews_csv(page: RuntimeHumanReviewPage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "human_review_id",
            "project_id",
            "target_type",
            "target_id",
            "review_status",
            "decision_hash",
            "reviewer_id_hash",
            "notes_hash",
            "payload_keys",
            "created_at",
            "audit_event_count",
            "latest_audit_event_type",
            "latest_audit_method_version",
            "latest_audit_after_hash",
        ],
    )
    writer.writeheader()
    for record in page.records:
        human_review = record.human_review
        latest_audit_event = _latest_audit_event(record.audit_events)
        payload = human_review.get("payload") if isinstance(human_review.get("payload"), dict) else {}
        decision = str(human_review.get("decision") or "")
        reviewer_id = str(human_review.get("reviewer_id") or "")
        notes = str(human_review.get("notes") or "")
        writer.writerow(
            {
                "human_review_id": human_review.get("id") or "",
                "project_id": human_review.get("project_id") or "",
                "target_type": human_review.get("target_type") or "",
                "target_id": human_review.get("target_id") or "",
                "review_status": human_review.get("review_status") or "",
                "decision_hash": _artifact_hash(decision) if decision else "",
                "reviewer_id_hash": _artifact_hash(reviewer_id) if reviewer_id else "",
                "notes_hash": _artifact_hash(notes) if notes else "",
                "payload_keys": "|".join(sorted(str(key) for key in payload)),
                "created_at": human_review.get("created_at") or "",
                "audit_event_count": len(record.audit_events),
                "latest_audit_event_type": latest_audit_event.get("event_type") or "",
                "latest_audit_method_version": latest_audit_event.get("method_version") or "",
                "latest_audit_after_hash": latest_audit_event.get("after_hash") or "",
            }
        )
    return output.getvalue()


def _render_runtime_score_snapshots_csv(page: RuntimeScoreSnapshotPage) -> str:
    def ordered_unique(values: tuple[object, ...] | list[object]) -> str:
        seen: set[str] = set()
        normalized: list[str] = []
        for value in values:
            text = str(value or "")
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return "|".join(normalized)

    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "score_snapshot_id",
            "project_id",
            "scope_type",
            "scope_value",
            "formula_version",
            "final_score",
            "trigger_rate",
            "mention_rate",
            "recommendation_rate",
            "dispersion",
            "platform_weights_keys",
            "component_weights_keys",
            "snapshot_answer_run_count",
            "linked_answer_run_count",
            "linked_answer_run_ids",
            "linked_prompt_text_hashes",
            "linked_prompt_versions",
            "linked_platforms",
            "linked_cities",
            "linked_collector_versions",
            "linked_analysis_versions",
            "linked_analysis_payload_hashes",
            "score_contribution_id",
            "component_name",
            "component_score",
            "component_weight",
            "weighted_contribution",
            "denominator",
            "evidence_answer_run_count",
            "evidence_answer_run_ids",
            "positive_evidence_summary_hash",
            "negative_evidence_summary_hash",
            "confidence_note_hash",
            "created_at",
            "audit_event_count",
            "latest_audit_event_type",
            "latest_audit_method_version",
            "latest_audit_after_hash",
        ],
    )
    writer.writeheader()
    for record in page.records:
        snapshot = record.snapshot
        latest_audit_event = _latest_audit_event(record.audit_events)
        snapshot_answer_run_ids = snapshot.get("answer_run_ids")
        if not isinstance(snapshot_answer_run_ids, (list, tuple)):
            snapshot_answer_run_ids = ()
        linked_runs = tuple(run.answer_run for run in record.answer_runs)
        linked_analyses = tuple(run.analysis for run in record.answer_runs if run.analysis)
        platform_weights = snapshot.get("platform_weights_snapshot")
        component_weights = snapshot.get("component_weights_snapshot")
        base_row = {
            "score_snapshot_id": snapshot.get("id") or "",
            "project_id": snapshot.get("project_id") or "",
            "scope_type": snapshot.get("scope_type") or "",
            "scope_value": snapshot.get("scope_value") or "",
            "formula_version": snapshot.get("formula_version") or "",
            "final_score": snapshot.get("final_score") if snapshot.get("final_score") is not None else "",
            "trigger_rate": snapshot.get("trigger_rate") if snapshot.get("trigger_rate") is not None else "",
            "mention_rate": snapshot.get("mention_rate") if snapshot.get("mention_rate") is not None else "",
            "recommendation_rate": snapshot.get("recommendation_rate")
            if snapshot.get("recommendation_rate") is not None
            else "",
            "dispersion": snapshot.get("dispersion") if snapshot.get("dispersion") is not None else "",
            "platform_weights_keys": "|".join(sorted(str(key) for key in platform_weights))
            if isinstance(platform_weights, dict)
            else "",
            "component_weights_keys": "|".join(sorted(str(key) for key in component_weights))
            if isinstance(component_weights, dict)
            else "",
            "snapshot_answer_run_count": len(snapshot_answer_run_ids),
            "linked_answer_run_count": len(linked_runs),
            "linked_answer_run_ids": ordered_unique([run.get("id") for run in linked_runs]),
            "linked_prompt_text_hashes": ordered_unique(
                [_hash_text_field(run.get("prompt_text")) for run in linked_runs]
            ),
            "linked_prompt_versions": ordered_unique([run.get("prompt_version") for run in linked_runs]),
            "linked_platforms": ordered_unique([run.get("platform") for run in linked_runs]),
            "linked_cities": ordered_unique([run.get("city") for run in linked_runs]),
            "linked_collector_versions": ordered_unique([run.get("collector_version") for run in linked_runs]),
            "linked_analysis_versions": ordered_unique([analysis.get("analysis_version") for analysis in linked_analyses]),
            "linked_analysis_payload_hashes": ordered_unique(
                [
                    _artifact_hash(json.dumps(analysis.get("payload") or {}, ensure_ascii=False, sort_keys=True))
                    for analysis in linked_analyses
                ]
            ),
            "created_at": snapshot.get("created_at") or "",
            "audit_event_count": len(record.audit_events),
            "latest_audit_event_type": latest_audit_event.get("event_type") or "",
            "latest_audit_method_version": latest_audit_event.get("method_version") or "",
            "latest_audit_after_hash": latest_audit_event.get("after_hash") or "",
        }
        contributions = record.contributions or ({},)
        for contribution in contributions:
            evidence_answer_run_ids = contribution.get("evidence_answer_run_ids")
            if not isinstance(evidence_answer_run_ids, (list, tuple)):
                evidence_answer_run_ids = ()
            writer.writerow(
                {
                    **base_row,
                    "score_contribution_id": contribution.get("id") or "",
                    "component_name": contribution.get("component_name") or "",
                    "component_score": contribution.get("component_score")
                    if contribution.get("component_score") is not None
                    else "",
                    "component_weight": contribution.get("weight") if contribution.get("weight") is not None else "",
                    "weighted_contribution": contribution.get("weighted_contribution")
                    if contribution.get("weighted_contribution") is not None
                    else "",
                    "denominator": contribution.get("denominator") or "",
                    "evidence_answer_run_count": len(evidence_answer_run_ids),
                    "evidence_answer_run_ids": _pipe_join(evidence_answer_run_ids),
                    "positive_evidence_summary_hash": _hash_text_field(contribution.get("positive_evidence_summary")),
                    "negative_evidence_summary_hash": _hash_text_field(contribution.get("negative_evidence_summary")),
                    "confidence_note_hash": _hash_text_field(contribution.get("confidence_note")),
                }
            )
    return output.getvalue()


def _render_runtime_content_engines_csv(page: RuntimeContentEnginePage) -> str:
    def ordered_unique(values: tuple[object, ...] | list[object]) -> str:
        seen: set[str] = set()
        normalized: list[str] = []
        for value in values:
            text = str(value or "")
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return "|".join(normalized)

    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "project_id",
            "knowledge_fact_count",
            "knowledge_fact_ids",
            "knowledge_fact_types",
            "knowledge_fact_content_hashes",
            "approved_knowledge_fact_count",
            "connector_count",
            "connector_providers",
            "connector_statuses",
            "project_manual_distribution_count",
            "content_draft_id",
            "draft_title_hash",
            "content_type",
            "content_template_id",
            "target_city",
            "target_platform",
            "target_source_type",
            "source_gap_types",
            "review_status",
            "created_by_hash",
            "draft_markdown_hash",
            "target_question_count",
            "target_question_ids",
            "target_question_prompt_versions",
            "target_question_text_hashes",
            "used_knowledge_fact_count",
            "used_knowledge_fact_ids",
            "evidence_answer_run_count",
            "evidence_answer_run_ids",
            "evidence_prompt_text_hashes",
            "evidence_platforms",
            "evidence_cities",
            "source_action_id",
            "source_action_title_hash",
            "source_action_description_hash",
            "source_action_priority",
            "source_action_status",
            "manual_distribution_count",
            "manual_distribution_platforms",
            "manual_distribution_statuses",
            "manual_distribution_target_url_hashes",
            "manual_distribution_notes_hashes",
            "created_at",
            "draft_audit_event_count",
            "latest_draft_audit_event_type",
            "latest_draft_audit_method_version",
            "latest_draft_audit_after_hash",
            "engine_audit_event_count",
            "latest_engine_audit_event_type",
            "latest_engine_audit_method_version",
            "latest_engine_audit_after_hash",
        ],
    )
    writer.writeheader()
    for record in page.records:
        latest_engine_audit_event = _latest_audit_event(record.audit_events)
        project_distribution_records = record.manual_distribution_records
        knowledge_fact_content_hashes = [
            _artifact_hash(
                "|".join(
                    str(fact.get(field) or "")
                    for field in ("market_code", "fact_type", "subject", "predicate", "object_value", "city")
                )
            )
            for fact in record.knowledge_facts
        ]
        base_row = {
            "project_id": record.project_id,
            "knowledge_fact_count": len(record.knowledge_facts),
            "knowledge_fact_ids": ordered_unique([fact.get("id") for fact in record.knowledge_facts]),
            "knowledge_fact_types": ordered_unique([fact.get("fact_type") for fact in record.knowledge_facts]),
            "knowledge_fact_content_hashes": ordered_unique(knowledge_fact_content_hashes),
            "approved_knowledge_fact_count": sum(
                1
                for fact in record.knowledge_facts
                if str(fact.get("status") or "").lower() == KNOWLEDGE_FACT_APPROVED_STATUS
            ),
            "connector_count": len(record.integration_connectors),
            "connector_providers": ordered_unique([connector.get("provider") for connector in record.integration_connectors]),
            "connector_statuses": ordered_unique(
                [connector.get("connection_status") for connector in record.integration_connectors]
            ),
            "project_manual_distribution_count": len(project_distribution_records),
            "engine_audit_event_count": len(record.audit_events),
            "latest_engine_audit_event_type": latest_engine_audit_event.get("event_type") or "",
            "latest_engine_audit_method_version": latest_engine_audit_event.get("method_version") or "",
            "latest_engine_audit_after_hash": latest_engine_audit_event.get("after_hash") or "",
        }
        content_drafts = record.content_drafts or (None,)
        for runtime_draft in content_drafts:
            if runtime_draft is None:
                writer.writerow(base_row)
                continue
            draft = runtime_draft.draft
            latest_draft_audit_event = _latest_audit_event(runtime_draft.audit_events)
            action = runtime_draft.action_recommendation or {}
            writer.writerow(
                {
                    **base_row,
                    "content_draft_id": draft.get("id") or "",
                    "draft_title_hash": _hash_text_field(draft.get("title")),
                    "content_type": draft.get("content_type") or "",
                    "content_template_id": draft.get("content_template_id") or "",
                    "target_city": draft.get("target_city") or "",
                    "target_platform": draft.get("target_platform") or "",
                    "target_source_type": draft.get("target_source_type") or "",
                    "source_gap_types": _pipe_join(draft.get("source_gap_types")),
                    "review_status": draft.get("review_status") or "",
                    "created_by_hash": _hash_text_field(draft.get("created_by")),
                    "draft_markdown_hash": _hash_text_field(draft.get("draft_markdown")),
                    "target_question_count": len(runtime_draft.target_questions),
                    "target_question_ids": ordered_unique([question.get("id") for question in runtime_draft.target_questions]),
                    "target_question_prompt_versions": ordered_unique(
                        [question.get("prompt_version") for question in runtime_draft.target_questions]
                    ),
                    "target_question_text_hashes": ordered_unique(
                        [_hash_text_field(question.get("text")) for question in runtime_draft.target_questions]
                    ),
                    "used_knowledge_fact_count": len(runtime_draft.knowledge_facts),
                    "used_knowledge_fact_ids": ordered_unique([fact.get("id") for fact in runtime_draft.knowledge_facts]),
                    "evidence_answer_run_count": len(runtime_draft.answer_runs),
                    "evidence_answer_run_ids": ordered_unique([run.get("id") for run in runtime_draft.answer_runs]),
                    "evidence_prompt_text_hashes": ordered_unique(
                        [_hash_text_field(run.get("prompt_text")) for run in runtime_draft.answer_runs]
                    ),
                    "evidence_platforms": ordered_unique([run.get("platform") for run in runtime_draft.answer_runs]),
                    "evidence_cities": ordered_unique([run.get("city") for run in runtime_draft.answer_runs]),
                    "source_action_id": action.get("id") or "",
                    "source_action_title_hash": _hash_text_field(action.get("title")),
                    "source_action_description_hash": _hash_text_field(action.get("description")),
                    "source_action_priority": action.get("priority") or "",
                    "source_action_status": action.get("status") or "",
                    "manual_distribution_count": len(runtime_draft.manual_distribution_records),
                    "manual_distribution_platforms": ordered_unique(
                        [row.get("platform") for row in runtime_draft.manual_distribution_records]
                    ),
                    "manual_distribution_statuses": ordered_unique(
                        [row.get("status") for row in runtime_draft.manual_distribution_records]
                    ),
                    "manual_distribution_target_url_hashes": ordered_unique(
                        [_hash_text_field(row.get("target_url")) for row in runtime_draft.manual_distribution_records]
                    ),
                    "manual_distribution_notes_hashes": ordered_unique(
                        [_hash_text_field(row.get("notes")) for row in runtime_draft.manual_distribution_records]
                    ),
                    "created_at": draft.get("created_at") or "",
                    "draft_audit_event_count": len(runtime_draft.audit_events),
                    "latest_draft_audit_event_type": latest_draft_audit_event.get("event_type") or "",
                    "latest_draft_audit_method_version": latest_draft_audit_event.get("method_version") or "",
                    "latest_draft_audit_after_hash": latest_draft_audit_event.get("after_hash") or "",
                }
            )
    return output.getvalue()


def _render_runtime_traceability_csv(detail: RuntimeTraceabilityDetail) -> str:
    bundle = detail.traceability_bundle
    latest_audit_event = _latest_audit_event(detail.audit_events)
    score_contribution_count = sum(len(snapshot.contributions) for snapshot in detail.score_snapshots)
    citation_count = sum(len(run.citations) for run in detail.evidence_runs)
    asset_count = sum(len(run.evidence_assets) for run in detail.evidence_runs)
    raw_payload_hashes = _pipe_join(
        [
            run.raw_answer.get("raw_payload_hash")
            for run in detail.evidence_runs
            if run.raw_answer and run.raw_answer.get("raw_payload_hash")
        ]
    )
    answer_prompt_text_hashes = _pipe_join(
        [_hash_text_field(run.answer_run.get("prompt_text")) for run in detail.evidence_runs]
    )
    source_domains = (
        _pipe_join([node.node.get("source_domain") for node in detail.citation_graph.nodes])
        if detail.citation_graph
        else ""
    )
    source_gap_types = (
        _pipe_join([gap.get("gap_type") or gap.get("source_gap_type") for gap in detail.citation_graph.source_gaps])
        if detail.citation_graph
        else _pipe_join(bundle.get("source_gap_types"))
    )
    action_title_hashes = _pipe_join(
        [_hash_text_field(action.get("title")) for action in detail.action_recommendations]
    )
    content_draft_title_hashes = _pipe_join(
        [_hash_text_field(record.draft.get("title")) for record in detail.content_drafts]
    )
    content_draft_markdown_hashes = _pipe_join(
        [_hash_text_field(record.draft.get("draft_markdown")) for record in detail.content_drafts]
    )
    base_row = {
        "traceability_bundle_id": bundle.get("id") or "",
        "project_id": bundle.get("project_id") or "",
        "subject_type": bundle.get("subject_type") or "",
        "subject_id": bundle.get("subject_id") or "",
        "report_export_count": len(bundle.get("report_export_ids") or ()),
        "report_export_ids": _pipe_join(bundle.get("report_export_ids")),
        "score_snapshot_count": len(bundle.get("score_snapshot_ids") or ()),
        "score_snapshot_ids": _pipe_join(bundle.get("score_snapshot_ids")),
        "score_contribution_count": score_contribution_count,
        "score_contribution_ids": _pipe_join(bundle.get("score_contribution_ids")),
        "answer_run_count": len(bundle.get("answer_run_ids") or ()),
        "answer_run_ids": _pipe_join(bundle.get("answer_run_ids")),
        "raw_answer_count": len(bundle.get("raw_answer_ids") or ()),
        "raw_answer_ids": _pipe_join(bundle.get("raw_answer_ids")),
        "citation_count": citation_count,
        "answer_citation_ids": _pipe_join(bundle.get("answer_citation_ids")),
        "asset_count": asset_count,
        "evidence_asset_ids": _pipe_join(bundle.get("evidence_asset_ids")),
        "source_graph_count": len(bundle.get("source_graph_ids") or ()),
        "source_graph_ids": _pipe_join(bundle.get("source_graph_ids")),
        "source_domains": source_domains,
        "source_gap_types": source_gap_types,
        "action_count": len(bundle.get("action_recommendation_ids") or ()),
        "action_recommendation_ids": _pipe_join(bundle.get("action_recommendation_ids")),
        "action_title_hashes": action_title_hashes,
        "content_draft_count": len(bundle.get("content_draft_ids") or ()),
        "content_draft_ids": _pipe_join(bundle.get("content_draft_ids")),
        "content_draft_title_hashes": content_draft_title_hashes,
        "content_draft_markdown_hashes": content_draft_markdown_hashes,
        "audit_event_count": len(detail.audit_events),
        "audit_event_ids": _pipe_join(bundle.get("audit_event_ids")),
        "latest_audit_event_type": latest_audit_event.get("event_type") or "",
        "latest_audit_method_version": latest_audit_event.get("method_version") or "",
        "latest_audit_after_hash": latest_audit_event.get("after_hash") or "",
        "explanation_summary_hash": _hash_text_field(bundle.get("explanation_summary")),
        "raw_payload_hashes": raw_payload_hashes,
        "answer_prompt_text_hashes": answer_prompt_text_hashes,
    }
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            *base_row.keys(),
            "evidence_link_id",
            "evidence_link_source_type",
            "evidence_link_source_id",
            "evidence_link_target_type",
            "evidence_link_target_id",
            "evidence_link_relation_type",
            "evidence_link_answer_run_count",
            "evidence_link_answer_run_ids",
        ],
    )
    writer.writeheader()
    evidence_links = detail.evidence_links or ({},)
    for link in evidence_links:
        writer.writerow(
            {
                **base_row,
                "evidence_link_id": link.get("id") or "",
                "evidence_link_source_type": link.get("source_type") or "",
                "evidence_link_source_id": link.get("source_id") or "",
                "evidence_link_target_type": link.get("target_type") or "",
                "evidence_link_target_id": link.get("target_id") or "",
                "evidence_link_relation_type": link.get("relation_type") or "",
                "evidence_link_answer_run_count": len(link.get("answer_run_ids") or ()),
                "evidence_link_answer_run_ids": _pipe_join(link.get("answer_run_ids")),
            }
        )
    return output.getvalue()


def _render_runtime_citation_graphs_csv(page: RuntimeCitationGraphPage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "project_id",
            "source_node_count",
            "evidence_link_count",
            "source_gap_count",
            "competitor_benchmark_count",
            "source_graph_id",
            "source_url_hash",
            "source_domain",
            "source_type",
            "topic",
            "source_gap_type",
            "citation_count",
            "source_answer_run_count",
            "source_answer_run_ids",
            "source_prompt_text_hashes",
            "source_prompt_versions",
            "source_platforms",
            "source_cities",
            "graph_evidence_link_count",
            "graph_evidence_link_ids",
            "graph_evidence_relation_types",
            "graph_evidence_answer_run_ids",
            "graph_evidence_citation_ids",
            "source_gap_ids",
            "source_gap_types",
            "source_gap_source_types",
            "source_gap_observed_counts",
            "source_gap_expected_weights",
            "source_gap_recommendation_hashes",
            "competitor_benchmark_ids",
            "competitor_names",
            "competitor_metric_scopes",
            "competitor_payload_keys",
            "competitor_payload_hashes",
            "competitor_answer_run_ids",
            "created_at",
        ],
    )
    writer.writeheader()
    for graph in page.records:
        graph_evidence_by_source: dict[str, list[dict[str, Any]]] = {}
        for link in graph.evidence_links:
            graph_evidence_by_source.setdefault(str(link.get("source_graph_id") or ""), []).append(link)
        base_row = {
            "project_id": graph.project_id,
            "source_node_count": len(graph.nodes),
            "evidence_link_count": len(graph.evidence_links),
            "source_gap_count": len(graph.source_gaps),
            "competitor_benchmark_count": len(graph.competitor_benchmarks),
            "source_gap_ids": _pipe_join([gap.get("id") for gap in graph.source_gaps]),
            "source_gap_types": _pipe_join([gap.get("gap_type") for gap in graph.source_gaps]),
            "source_gap_source_types": _pipe_join([gap.get("source_type") for gap in graph.source_gaps]),
            "source_gap_observed_counts": _pipe_join([gap.get("observed_count") for gap in graph.source_gaps]),
            "source_gap_expected_weights": _pipe_join([gap.get("expected_weight") for gap in graph.source_gaps]),
            "source_gap_recommendation_hashes": _pipe_join(
                [_hash_text_field(gap.get("recommendation")) for gap in graph.source_gaps]
            ),
            "competitor_benchmark_ids": _pipe_join(
                [benchmark.get("id") for benchmark in graph.competitor_benchmarks]
            ),
            "competitor_names": _pipe_join(
                [benchmark.get("competitor_name") for benchmark in graph.competitor_benchmarks]
            ),
            "competitor_metric_scopes": _pipe_join(
                [benchmark.get("metric_scope") for benchmark in graph.competitor_benchmarks]
            ),
            "competitor_payload_keys": _pipe_join(
                [
                    "|".join(sorted(str(key) for key in (benchmark.get("payload") or {})))
                    if isinstance(benchmark.get("payload"), dict)
                    else ""
                    for benchmark in graph.competitor_benchmarks
                ]
            ),
            "competitor_payload_hashes": _pipe_join(
                [
                    _artifact_hash(json.dumps(benchmark.get("payload") or {}, ensure_ascii=False, sort_keys=True))
                    for benchmark in graph.competitor_benchmarks
                ]
            ),
            "competitor_answer_run_ids": _pipe_join(
                [
                    _pipe_join(benchmark.get("answer_run_ids"))
                    for benchmark in graph.competitor_benchmarks
                ]
            ),
        }
        nodes = graph.nodes or (RuntimeCitationGraphNode(node={}, answer_runs=()),)
        for item in nodes:
            node = item.node
            answer_runs = item.answer_runs
            source_graph_id = str(node.get("id") or "")
            links = tuple(graph_evidence_by_source.get(source_graph_id, ()))
            writer.writerow(
                {
                    **base_row,
                    "source_graph_id": source_graph_id,
                    "source_url_hash": _hash_text_field(node.get("source_url")),
                    "source_domain": node.get("source_domain") or "",
                    "source_type": node.get("source_type") or "",
                    "topic": node.get("topic") or "",
                    "source_gap_type": node.get("source_gap_type") or "",
                    "citation_count": node.get("citation_count") or "",
                    "source_answer_run_count": len(answer_runs),
                    "source_answer_run_ids": _pipe_join([run.get("id") for run in answer_runs]),
                    "source_prompt_text_hashes": _pipe_join(
                        [_hash_text_field(run.get("prompt_text")) for run in answer_runs]
                    ),
                    "source_prompt_versions": _pipe_join([run.get("prompt_version") for run in answer_runs]),
                    "source_platforms": _pipe_join([run.get("platform") for run in answer_runs]),
                    "source_cities": _pipe_join([run.get("city") for run in answer_runs]),
                    "graph_evidence_link_count": len(links),
                    "graph_evidence_link_ids": _pipe_join([link.get("id") for link in links]),
                    "graph_evidence_relation_types": _pipe_join([link.get("relation_type") for link in links]),
                    "graph_evidence_answer_run_ids": _pipe_join([link.get("answer_run_id") for link in links]),
                    "graph_evidence_citation_ids": _pipe_join([link.get("answer_citation_id") for link in links]),
                    "created_at": node.get("created_at") or "",
                }
            )
    return output.getvalue()


def _render_runtime_action_plans_csv(page: RuntimeActionPlanPage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "action_recommendation_id",
            "project_id",
            "retest_schedule_id",
            "prompt_version",
            "priority",
            "status",
            "owner_id_hash",
            "source_gap_type",
            "related_source_types",
            "title_hash",
            "description_hash",
            "evidence_answer_run_count",
            "schedule_answer_run_count",
            "sample_size",
            "offsets_days",
            "scheduled_date_count",
            "next_check_date",
            "action_created_at",
            "schedule_created_at",
            "latest_retest_comparison_id",
            "latest_retest_trend",
            "latest_baseline_score",
            "latest_retest_score",
            "latest_score_delta",
            "latest_retest_created_at",
            "answer_run_count",
            "audit_event_count",
            "latest_audit_event_type",
            "latest_audit_method_version",
            "latest_audit_after_hash",
        ],
    )
    writer.writeheader()
    for record in page.records:
        schedule = record.retest_schedule
        latest_comparison = record.retest_comparisons[0] if record.retest_comparisons else {}
        latest_audit_event = _latest_audit_event(record.audit_events)
        schedule_answer_run_ids = schedule.get("answer_run_ids")
        if not isinstance(schedule_answer_run_ids, (list, tuple)):
            schedule_answer_run_ids = ()
        offsets_days = schedule.get("offsets_days")
        if not isinstance(offsets_days, (list, tuple)):
            offsets_days = ()
        scheduled_dates = schedule.get("scheduled_dates")
        if not isinstance(scheduled_dates, (list, tuple)):
            scheduled_dates = ()
        actions = record.action_recommendations or ({},)
        for action in actions:
            related_source_types = action.get("related_source_types") if isinstance(action, dict) else ()
            if not isinstance(related_source_types, (list, tuple)):
                related_source_types = ()
            evidence_answer_run_ids = action.get("evidence_answer_run_ids") if isinstance(action, dict) else ()
            if not isinstance(evidence_answer_run_ids, (list, tuple)):
                evidence_answer_run_ids = ()
            owner_id = str(action.get("owner_id") or "") if isinstance(action, dict) else ""
            title = str(action.get("title") or "") if isinstance(action, dict) else ""
            description = str(action.get("description") or "") if isinstance(action, dict) else ""
            writer.writerow(
                {
                    "action_recommendation_id": action.get("id") or "" if isinstance(action, dict) else "",
                    "project_id": schedule.get("project_id") or "",
                    "retest_schedule_id": schedule.get("id") or "",
                    "prompt_version": schedule.get("prompt_version") or "",
                    "priority": action.get("priority") or "" if isinstance(action, dict) else "",
                    "status": action.get("status") or "" if isinstance(action, dict) else "",
                    "owner_id_hash": _artifact_hash(owner_id) if owner_id else "",
                    "source_gap_type": action.get("source_gap_type") or "" if isinstance(action, dict) else "",
                    "related_source_types": "|".join(str(source_type) for source_type in related_source_types),
                    "title_hash": _artifact_hash(title) if title else "",
                    "description_hash": _artifact_hash(description) if description else "",
                    "evidence_answer_run_count": len(evidence_answer_run_ids),
                    "schedule_answer_run_count": len(schedule_answer_run_ids),
                    "sample_size": schedule.get("sample_size") or 0,
                    "offsets_days": "|".join(str(offset_day) for offset_day in offsets_days),
                    "scheduled_date_count": len(scheduled_dates),
                    "next_check_date": action.get("next_check_date") or "" if isinstance(action, dict) else "",
                    "action_created_at": action.get("created_at") or "" if isinstance(action, dict) else "",
                    "schedule_created_at": schedule.get("created_at") or "",
                    "latest_retest_comparison_id": latest_comparison.get("id") or "",
                    "latest_retest_trend": latest_comparison.get("trend") or "",
                    "latest_baseline_score": latest_comparison.get("baseline_score") or "",
                    "latest_retest_score": latest_comparison.get("retest_score") or "",
                    "latest_score_delta": latest_comparison.get("score_delta") or "",
                    "latest_retest_created_at": latest_comparison.get("created_at") or "",
                    "answer_run_count": len(record.answer_runs),
                    "audit_event_count": len(record.audit_events),
                    "latest_audit_event_type": latest_audit_event.get("event_type") or "",
                    "latest_audit_method_version": latest_audit_event.get("method_version") or "",
                    "latest_audit_after_hash": latest_audit_event.get("after_hash") or "",
                }
            )
    return output.getvalue()


def _render_runtime_alerts_csv(page: RuntimeAlertPage) -> str:
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "alert_id",
            "project_id",
            "alert_type",
            "severity",
            "metric_name",
            "metric_value",
            "threshold",
            "rule_version",
            "source",
            "source_id",
            "title_hash",
            "summary_hash",
            "created_at",
            "evidence_ref_count",
            "evidence_ref_types",
            "evidence_ref_target_ids",
            "related_action_count",
            "related_action_ids",
            "related_action_title_hashes",
            "management_event_count",
            "latest_management_event_id",
            "latest_management_status",
            "latest_management_updated_by_hash",
            "latest_management_note_hash",
            "latest_management_metadata_keys",
            "latest_management_created_at",
            "audit_event_count",
            "latest_audit_event_type",
            "latest_audit_method_version",
            "latest_audit_after_hash",
        ],
    )
    writer.writeheader()
    for record in page.records:
        alert = record.alert
        evidence_ref_types = tuple(
            sorted({str(ref.get("target_type") or "") for ref in record.evidence_refs if ref.get("target_type")})
        )
        evidence_ref_target_ids = tuple(
            str(ref.get("target_id") or "") for ref in record.evidence_refs if ref.get("target_id")
        )
        related_action_ids = tuple(
            str(action.get("id") or "") for action in record.related_actions if action.get("id")
        )
        related_action_title_hashes = tuple(
            _artifact_hash(str(action.get("title") or ""))
            for action in record.related_actions
            if str(action.get("title") or "")
        )
        latest_management_event = _latest_audit_event(record.management_events)
        latest_audit_event = _latest_audit_event(record.audit_events)
        management_metadata = (
            latest_management_event.get("metadata")
            if isinstance(latest_management_event.get("metadata"), dict)
            else {}
        )
        title = str(alert.get("title") or "")
        summary = str(alert.get("summary") or "")
        updated_by = str(latest_management_event.get("updated_by") or "")
        note = str(latest_management_event.get("note") or "")
        writer.writerow(
            {
                "alert_id": alert.get("id") or "",
                "project_id": alert.get("project_id") or "",
                "alert_type": alert.get("alert_type") or "",
                "severity": alert.get("severity") or "",
                "metric_name": alert.get("metric_name") or "",
                "metric_value": alert.get("metric_value") if alert.get("metric_value") is not None else "",
                "threshold": alert.get("threshold") if alert.get("threshold") is not None else "",
                "rule_version": alert.get("rule_version") or "",
                "source": alert.get("source") or "",
                "source_id": alert.get("source_id") or "",
                "title_hash": _artifact_hash(title) if title else "",
                "summary_hash": _artifact_hash(summary) if summary else "",
                "created_at": alert.get("created_at") or "",
                "evidence_ref_count": len(record.evidence_refs),
                "evidence_ref_types": "|".join(evidence_ref_types),
                "evidence_ref_target_ids": "|".join(evidence_ref_target_ids),
                "related_action_count": len(record.related_actions),
                "related_action_ids": "|".join(related_action_ids),
                "related_action_title_hashes": "|".join(related_action_title_hashes),
                "management_event_count": len(record.management_events),
                "latest_management_event_id": latest_management_event.get("id") or "",
                "latest_management_status": latest_management_event.get("status") or "",
                "latest_management_updated_by_hash": _artifact_hash(updated_by) if updated_by else "",
                "latest_management_note_hash": _artifact_hash(note) if note else "",
                "latest_management_metadata_keys": "|".join(sorted(str(key) for key in management_metadata)),
                "latest_management_created_at": latest_management_event.get("created_at") or "",
                "audit_event_count": len(record.audit_events),
                "latest_audit_event_type": latest_audit_event.get("event_type") or "",
                "latest_audit_method_version": latest_audit_event.get("method_version") or "",
                "latest_audit_after_hash": latest_audit_event.get("after_hash") or "",
            }
        )
    return output.getvalue()


ANSWER_RUN_COLUMNS = (
    "id",
    "project_id",
    "prompt_question_id",
    "platform",
    "surface",
    "access_method",
    "market_code",
    "city",
    "language",
    "device",
    "answer_present",
    "surface_triggered",
    "sample_index",
    "sample_size",
    "model_or_surface",
    "account_state",
    "collector_backend_id",
    "collector_version",
    "collected_at",
    "status",
)
ANSWER_RUN_READ_COLUMNS = ANSWER_RUN_COLUMNS + (
    "prompt_text",
    "prompt_intent_type",
    "prompt_priority",
    "prompt_version",
)
TENANT_COLUMNS = ("id", "name", "slug", "created_at")
PROJECT_COLUMNS = (
    "id",
    "tenant_id",
    "name",
    "market_code",
    "industry_code",
    "target_brand",
    "category",
    "prompt_version",
    "status",
    "created_at",
)
PROJECT_MEMBER_COLUMNS = (
    "id",
    "project_id",
    "user_id",
    "role",
    "created_at",
)
PROJECT_MEMBER_INVITATION_COLUMNS = (
    "id",
    "project_id",
    "email",
    "role",
    "status",
    "invite_token_hash",
    "invited_by",
    "expires_at",
    "accepted_at",
    "revoked_at",
    "metadata",
    "created_at",
    "updated_at",
)
BRAND_ENTITY_COLUMNS = (
    "id",
    "project_id",
    "canonical_name",
    "official_domains",
    "parent_company",
    "product_lines",
    "status",
)
COMPETITOR_ENTITY_COLUMNS = (
    "id",
    "project_id",
    "canonical_name",
    "official_domains",
    "parent_company",
    "product_lines",
    "status",
)
ENTITY_ALIAS_COLUMNS = (
    "id",
    "entity_id",
    "entity_kind",
    "alias",
    "alias_type",
    "confidence",
    "confirmed_by",
    "created_at",
)
ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS = (
    "id",
    "project_id",
    "candidate_id",
    "entity_id",
    "entity_kind",
    "alias",
    "alias_type",
    "source",
    "confidence",
    "decision",
    "reviewed_by",
    "reason",
    "notes",
    "assigned_to",
    "assigned_by",
    "assignment_status",
    "assignment_note",
    "assigned_at",
    "due_at",
    "priority",
    "evidence_answer_run_ids",
    "evidence_urls",
    "payload",
    "created_at",
    "updated_at",
)
ENTITY_ALIAS_JOIN_COLUMNS = ENTITY_ALIAS_COLUMNS + (
    "project_id",
    "canonical_name",
    "official_domains",
    "parent_company",
    "product_lines",
    "status",
)
RAW_ANSWER_COLUMNS = ("id", "answer_run_id", "answer_text", "raw_payload", "raw_payload_hash", "created_at")
CITATION_COLUMNS = ("id", "answer_run_id", "url", "domain", "position", "source_type", "created_at")
ASSET_COLUMNS = (
    "id",
    "tenant_id",
    "project_id",
    "answer_run_id",
    "asset_type",
    "url",
    "content_hash",
    "storage_backend",
    "storage_key",
    "bucket",
    "content_type",
    "byte_size",
    "metadata",
    "visibility",
    "created_by",
    "created_at",
    "updated_at",
)
COLLECTOR_LOG_COLUMNS = (
    "id",
    "answer_run_id",
    "collector_backend_id",
    "event_type",
    "payload",
    "created_at",
)
COLLECTION_COST_COLUMNS = (
    "id",
    "answer_run_id",
    "project_id",
    "collector_backend_id",
    "llm_provider",
    "llm_tokens",
    "llm_cost",
    "proxy_or_vendor_cost",
    "compute_cost",
    "total_cost",
    "duration_ms",
    "created_at",
)
COLLECTION_RUN_SUMMARY_COLUMNS = (
    "id",
    "project_id",
    "run_type",
    "mode",
    "planned_runs",
    "attempted_runs",
    "success_count",
    "failure_count",
    "success_rate",
    "trigger_rate",
    "answer_present_rate",
    "total_cost",
    "average_cost_per_run",
    "total_duration_ms",
    "average_duration_ms",
    "collector_backend_ids",
    "platform_distribution",
    "city_distribution",
    "access_method_distribution",
    "failure_summary",
    "answer_run_ids",
    "started_at",
    "completed_at",
    "created_at",
)
API_BROWSER_FIDELITY_CHECK_COLUMNS = (
    "id",
    "project_id",
    "report_export_id",
    "status",
    "official_api_records",
    "browser_records",
    "comparable_prompt_city_pairs",
    "mismatch_count",
    "difference_rate",
    "payload",
    "payload_hash",
    "answer_run_ids",
    "checked_by",
    "checked_at",
)
VISIBILITY_SCORE_SNAPSHOT_COLUMNS = (
    "id",
    "project_id",
    "scope_type",
    "scope_value",
    "formula_version",
    "platform_weights_snapshot",
    "final_score",
    "trigger_rate",
    "mention_rate",
    "recommendation_rate",
    "answer_run_ids",
    "created_at",
    "dispersion",
    "component_weights_snapshot",
)
SCORE_CONTRIBUTION_COLUMNS = (
    "id",
    "score_snapshot_id",
    "component_name",
    "component_score",
    "weight",
    "weighted_contribution",
    "denominator",
    "evidence_answer_run_ids",
    "positive_evidence_summary",
    "negative_evidence_summary",
    "confidence_note",
    "created_at",
)
ANSWER_ANALYSIS_READ_COLUMNS = (
    "id",
    "answer_run_id",
    "parser_engine_id",
    "analysis_version",
    "payload",
    "confidence",
    "created_at",
)
SOURCE_GRAPH_COLUMNS = (
    "id",
    "project_id",
    "source_url",
    "source_domain",
    "source_type",
    "topic",
    "source_gap_type",
    "answer_run_ids",
    "citation_count",
    "created_at",
)
SOURCE_GRAPH_EVIDENCE_COLUMNS = (
    "id",
    "source_graph_id",
    "answer_run_id",
    "answer_citation_id",
    "relation_type",
    "created_at",
)
SOURCE_GAP_COLUMNS = (
    "id",
    "project_id",
    "source_type",
    "gap_type",
    "observed_count",
    "expected_weight",
    "recommendation",
    "created_at",
)
COMPETITOR_BENCHMARK_COLUMNS = (
    "id",
    "project_id",
    "competitor_name",
    "metric_scope",
    "payload",
    "answer_run_ids",
    "created_at",
)
REPORT_EXPORT_COLUMNS = (
    "id",
    "project_id",
    "market_code",
    "report_version",
    "report_type",
    "score_snapshot_ids",
    "answer_run_ids",
    "prompt_version",
    "scoring_formula_version",
    "platform_weights_snapshot",
    "method_disclosure",
    "sample_size",
    "window_start",
    "window_end",
    "methodology_hash",
    "markdown_url",
    "pdf_url",
    "csv_url",
    "exported_by",
    "exported_at",
)
REPORT_EXPORT_JOB_COLUMNS = (
    "id",
    "project_id",
    "report_export_id",
    "status",
    "artifact_type",
    "template",
    "filters",
    "sort",
    "requested_by",
    "requested_at",
    "started_at",
    "completed_at",
    "attempt_count",
    "max_attempts",
    "lease_expires_at",
    "next_attempt_at",
    "artifact_url",
    "error_message",
    "updated_by",
    "updated_at",
)
REPORT_EXPORT_JOB_RETURNING = ", ".join(REPORT_EXPORT_JOB_COLUMNS)
RUNTIME_NOTIFICATION_COLUMNS = (
    "id",
    "project_id",
    "notification_type",
    "severity",
    "title",
    "message",
    "target_type",
    "target_id",
    "recipient_role",
    "status",
    "payload",
    "created_by",
    "created_at",
    "read_at",
    "updated_by",
    "updated_at",
)
RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS = (
    "id",
    "project_id",
    "channel",
    "endpoint_url",
    "event_types",
    "severity_threshold",
    "status",
    "metadata",
    "created_by",
    "created_at",
    "updated_by",
    "updated_at",
)
RUNTIME_NOTIFICATION_DELIVERY_COLUMNS = (
    "id",
    "project_id",
    "notification_id",
    "subscription_id",
    "channel",
    "endpoint_url",
    "status",
    "attempt_count",
    "max_attempts",
    "lease_expires_at",
    "next_attempt_at",
    "response_status",
    "response_body_hash",
    "error_message",
    "payload",
    "created_at",
    "updated_by",
    "updated_at",
)
RUNTIME_NOTIFICATION_DELIVERY_RETURNING = ", ".join(RUNTIME_NOTIFICATION_DELIVERY_COLUMNS)
RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_COLUMNS = (
    "id",
    "project_id",
    "delivery_id",
    "notification_id",
    "subscription_id",
    "feedback_type",
    "recipient_hash",
    "provider",
    "provider_event_id_hash",
    "occurred_at",
    "metadata",
    "recorded_by",
    "created_at",
)
RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_RETURNING = ", ".join(RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_COLUMNS)
RUNTIME_NOTIFICATION_EMAIL_SUPPRESSION_COLUMNS = (
    "id",
    "project_id",
    "recipient_hash",
    "status",
    "source",
    "source_ref",
    "metadata",
    "created_by",
    "created_at",
    "updated_by",
    "updated_at",
)
RUNTIME_NOTIFICATION_EMAIL_SUPPRESSION_RETURNING = ", ".join(RUNTIME_NOTIFICATION_EMAIL_SUPPRESSION_COLUMNS)
RUNTIME_NOTIFICATION_SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}
RUNTIME_NOTIFICATION_SUBSCRIPTION_CHANNELS = {"webhook", "slack", "email"}
RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_TYPES = {"bounce", "complaint", "unsubscribe", "suppressed"}
RUNTIME_ALERT_EVENT_STATUSES = {"acknowledged", "resolved", "snoozed", "reopened", "escalated"}
RUNTIME_ALERT_EVENT_COLUMNS = (
    "id",
    "project_id",
    "alert_id",
    "alert_type",
    "source",
    "source_id",
    "status",
    "updated_by",
    "note",
    "metadata",
    "created_at",
)
ACTION_RECOMMENDATION_COLUMNS = (
    "id",
    "project_id",
    "title",
    "description",
    "priority",
    "status",
    "owner_id",
    "source_gap_type",
    "evidence_answer_run_ids",
    "related_source_types",
    "next_check_date",
    "created_at",
    "action_type",
    "customer_visible",
    "score_contribution_ids",
    "visibility_note",
)
RETEST_SCHEDULE_COLUMNS = (
    "id",
    "project_id",
    "prompt_version",
    "sample_size",
    "offsets_days",
    "scheduled_dates",
    "answer_run_ids",
    "created_at",
)
RETEST_COMPARISON_COLUMNS = (
    "id",
    "project_id",
    "baseline_score",
    "retest_score",
    "score_delta",
    "baseline_answer_run_ids",
    "retest_answer_run_ids",
    "trend",
    "created_at",
)
LOCALIZED_KNOWLEDGE_FACT_COLUMNS = (
    "id",
    "project_id",
    "market_code",
    "fact_type",
    "subject",
    "predicate",
    "object_value",
    "city",
    "evidence_source_id",
    "confidence",
    "status",
    "valid_from",
    "valid_until",
)
KNOWLEDGE_FACT_EMBEDDING_COLUMNS = (
    "id",
    "project_id",
    "knowledge_fact_id",
    "embedding_model",
    "content_hash",
    "created_at",
    "updated_at",
)
KNOWLEDGE_DOCUMENT_COLUMNS = (
    "id",
    "project_id",
    "source_type",
    "normalized_url",
    "source_url",
    "title",
    "raw_text",
    "content_hash",
    "status",
    "error_reason",
    "metadata",
    "imported_by",
    "created_at",
    "updated_at",
)
KNOWLEDGE_DOCUMENT_VERSION_COLUMNS = (
    "id",
    "project_id",
    "knowledge_document_id",
    "version_number",
    "normalized_url",
    "source_url",
    "title",
    "raw_text",
    "content_hash",
    "status",
    "crawl_adapter_version",
    "byte_size",
    "metadata",
    "created_by",
    "created_at",
)
KNOWLEDGE_GENERATION_JOB_COLUMNS = (
    "id",
    "project_id",
    "job_type",
    "status",
    "request_payload",
    "step_events",
    "generation_model",
    "generation_prompt_version",
    "secret_ref",
    "raw_output_hash",
    "error_reason",
    "requested_by",
    "started_at",
    "completed_at",
    "created_at",
    "updated_at",
)
PROMPT_CANDIDATE_COLUMNS = (
    "id",
    "project_id",
    "generation_job_id",
    "text",
    "intent_type",
    "market_code",
    "city",
    "language",
    "target_brand",
    "competitors",
    "priority",
    "intent_weight",
    "source_knowledge_fact_ids",
    "rationale",
    "duplicate_state",
    "review_status",
    "reviewed_by",
    "reviewed_at",
    "imported_prompt_id",
    "generation_model",
    "generation_prompt_version",
    "created_at",
    "updated_at",
)
FAQ_ANSWER_CANDIDATE_COLUMNS = (
    "id",
    "project_id",
    "generation_job_id",
    "question",
    "answer_markdown",
    "target_prompt_ids",
    "used_knowledge_fact_ids",
    "market_code",
    "city",
    "language",
    "review_status",
    "reviewed_by",
    "reviewed_at",
    "generation_model",
    "generation_prompt_version",
    "rationale",
    "created_at",
    "updated_at",
)
CONTENT_DRAFT_COLUMNS = (
    "id",
    "project_id",
    "title",
    "content_type",
    "content_template_id",
    "target_question_ids",
    "target_city",
    "target_platform",
    "target_source_type",
    "used_knowledge_fact_ids",
    "source_gap_types",
    "source_action_id",
    "evidence_answer_run_ids",
    "draft_markdown",
    "review_status",
    "created_by",
    "created_at",
)
INTEGRATION_CONNECTOR_COLUMNS = (
    "id",
    "project_id",
    "provider",
    "connection_status",
    "capabilities",
    "auth_mode",
    "created_at",
)
MANUAL_DISTRIBUTION_RECORD_COLUMNS = (
    "id",
    "project_id",
    "content_draft_id",
    "platform",
    "target_url",
    "status",
    "submitted_at",
    "checked_at",
    "notes",
)
PROMPT_QUESTION_READ_COLUMNS = (
    "id",
    "project_id",
    "market_code",
    "industry_code",
    "text",
    "intent_type",
    "city",
    "language",
    "target_brand",
    "competitors",
    "priority",
    "intent_weight",
    "prompt_version",
    "status",
)
AUDIT_EVENT_COLUMNS = (
    "id",
    "event_type",
    "project_id",
    "actor_type",
    "actor_id",
    "target_type",
    "target_id",
    "before_hash",
    "after_hash",
    "input_refs",
    "output_refs",
    "method_version",
    "reason",
    "created_at",
)
EVIDENCE_LINK_COLUMNS = (
    "id",
    "project_id",
    "source_type",
    "source_id",
    "target_type",
    "target_id",
    "relation_type",
    "answer_run_ids",
)
TRACEABILITY_BUNDLE_COLUMNS = (
    "id",
    "project_id",
    "subject_type",
    "subject_id",
    "report_export_ids",
    "score_snapshot_ids",
    "score_contribution_ids",
    "answer_run_ids",
    "raw_answer_ids",
    "answer_citation_ids",
    "evidence_asset_ids",
    "source_graph_ids",
    "source_gap_types",
    "action_recommendation_ids",
    "content_draft_ids",
    "audit_event_ids",
    "explanation_summary",
)
RUNTIME_SAVED_VIEW_COLUMNS = (
    "id",
    "project_id",
    "name",
    "view_type",
    "filters",
    "sort",
    "query_path",
    "export_path",
    "created_by",
    "created_at",
    "updated_at",
)
PROJECT_BRAND_KIT_COLUMNS = (
    "id",
    "project_id",
    "client_name",
    "prepared_by",
    "logo_url",
    "primary_color",
    "secondary_color",
    "footer_text",
    "updated_by",
    "created_at",
    "updated_at",
)
PROJECT_BRAND_ASSET_COLUMNS = (
    "id",
    "project_id",
    "asset_type",
    "asset_url",
    "category",
    "preview_url",
    "source_filename",
    "source_content_type",
    "content_hash",
    "storage_version",
    "status",
    "scan_status",
    "scan_checked_at",
    "scan_method_version",
    "scan_notes",
    "uploaded_by",
    "metadata",
    "created_at",
    "updated_at",
)
SCORE_WEIGHT_CONFIG_COLUMNS = (
    "id",
    "project_id",
    "formula_version",
    "weights",
    "updated_by",
    "notes",
    "created_at",
    "updated_at",
)
SCORE_WEIGHT_PROFILE_COLUMNS = (
    "id",
    "profile_key",
    "name",
    "description",
    "base_formula_version",
    "weights",
    "scope",
    "is_system",
    "status",
    "created_by",
    "updated_by",
    "created_at",
    "updated_at",
)
HUMAN_REVIEW_COLUMNS = (
    "id",
    "project_id",
    "target_type",
    "target_id",
    "review_status",
    "decision",
    "reviewer_id",
    "notes",
    "payload",
    "created_at",
)


class PostgresEvidenceRepository(RuntimeProjectAccessRepositoryMixin):
    """DB-API style repository for the GENO runtime evidence chain."""

    def __init__(
        self,
        connection: DbConnection,
        *,
        email_sender: Any | None = None,
        email_preference_base_url: str = "",
        email_preference_token_secret: str = "",
        email_preference_token_ttl_seconds: int = 2_592_000,
    ) -> None:
        self.connection = connection
        self.email_sender = email_sender
        self.email_preference_base_url = email_preference_base_url.strip()
        self.email_preference_token_secret = email_preference_token_secret
        self.email_preference_token_ttl_seconds = max(1, int(email_preference_token_ttl_seconds))

    def _knowledge_deepseek_api_key(self, secret_ref: str | None) -> str | None:
        if secret_ref:
            return self.resolve_connector_secret(secret_ref=secret_ref)
        return load_deepseek_api_key()

    def set_runtime_project_access_context(self, *, actor_id: str, project_id: str | None = None) -> None:
        actor_id = actor_id.strip()
        project_id = project_id.strip() if project_id else ""
        if not actor_id:
            raise ValueError("actor_id is required")
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  set_config(%s, %s, false),
                  set_config(%s, %s, false),
                  set_config(%s, %s, false),
                  set_config(%s, %s, false),
                  set_config(%s, %s, false),
                  set_config(%s, %s, false)
                """,
                (
                    "app.rls_enabled",
                    "1",
                    "app.actor_id",
                    actor_id,
                    "app.project_id",
                    project_id,
                    "geno.runtime_project_access_control",
                    "1",
                    "geno.runtime_actor_id",
                    actor_id,
                    "geno.runtime_project_id",
                    project_id,
                ),
            )

    def set_runtime_project_invitation_accept_context(self, *, invite_token_hash: str) -> None:
        invite_token_hash = invite_token_hash.strip()
        if not invite_token_hash:
            raise ValueError("invite_token_hash is required")
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  set_config(%s, %s, false),
                  set_config(%s, %s, false),
                  set_config(%s, %s, false),
                  set_config(%s, %s, false),
                  set_config(%s, %s, false),
                  set_config(%s, %s, false),
                  set_config(%s, %s, false)
                """,
                (
                    "app.rls_enabled",
                    "1",
                    "app.actor_id",
                    "",
                    "app.project_id",
                    "",
                    "geno.runtime_project_access_control",
                    "1",
                    "geno.runtime_actor_id",
                    "",
                    "geno.runtime_project_id",
                    "",
                    "geno.runtime_invitation_token_hash",
                    invite_token_hash,
                ),
            )

    def set_runtime_project_portal_token_context(self, *, portal_token_hash: str) -> None:
        portal_token_hash = portal_token_hash.strip()
        if not portal_token_hash:
            raise ValueError("portal_token_hash is required")
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  set_config(%s, %s, false),
                  set_config(%s, %s, false),
                  set_config(%s, %s, false),
                  set_config(%s, %s, false),
                  set_config(%s, %s, false),
                  set_config(%s, %s, false),
                  set_config(%s, %s, false)
                """,
                (
                    "app.rls_enabled",
                    "1",
                    "app.actor_id",
                    "",
                    "app.project_id",
                    "",
                    "geno.runtime_project_access_control",
                    "1",
                    "geno.runtime_actor_id",
                    "",
                    "geno.runtime_project_id",
                    "",
                    "geno.runtime_portal_token_hash",
                    portal_token_hash,
                ),
            )

    def list_runtime_projects(
        self,
        *,
        project_id: str | None = None,
        market_code: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
        actor_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeProjectPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("p.id = %s")
            params.append(_uuid(project_id))
        if market_code:
            filters.append("p.market_code = %s")
            params.append(market_code)
        normalized_status = status.strip().lower() if status else None
        if normalized_status:
            filters.append("p.status = %s")
            params.append(normalized_status)
        elif not include_archived:
            filters.append("p.status <> %s")
            params.append("archived")
        if actor_id:
            filters.append(
                """
                EXISTS (
                  SELECT 1
                  FROM project_members pm
                  WHERE pm.project_id = p.id AND pm.user_id = %s
                )
                """
            )
            params.append(actor_id)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*)
                FROM projects p
                {where_clause}
                """,
                tuple(params),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(f"p.{column}" for column in PROJECT_COLUMNS)}
                FROM projects p
                {where_clause}
                ORDER BY p.created_at DESC, p.id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            projects = _rows_dict(cursor.fetchall(), PROJECT_COLUMNS)
            records = tuple(self._load_runtime_project(cursor=cursor, project=project) for project in projects)
        return RuntimeProjectPage(total_count=total_count, limit=limit, offset=offset, records=records)

    def update_runtime_project(self, update: RuntimeProjectUpdateInput) -> RuntimeProject:
        project_id = update.project_id.strip()
        updated_by = update.updated_by.strip() or "runtime-console"
        if not project_id:
            raise ValueError("project_id is required")
        tenant_name = update.tenant_name.strip() if update.tenant_name is not None else None
        name = update.name.strip() if update.name is not None else None
        target_brand = update.target_brand.strip() if update.target_brand is not None else None
        category = update.category.strip() if update.category is not None else None
        status = update.status.strip().lower() if update.status is not None else None
        if tenant_name is not None and not tenant_name:
            raise ValueError("tenant_name cannot be empty")
        if name is not None and not name:
            raise ValueError("name cannot be empty")
        if target_brand is not None and not target_brand:
            raise ValueError("target_brand cannot be empty")
        if category is not None and not category:
            raise ValueError("category cannot be empty")
        if status is not None and status not in {"active", "paused"}:
            raise ValueError("status must be active or paused")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_COLUMNS)}
                FROM projects
                WHERE id = %s
                FOR UPDATE
                """,
                (_uuid(project_id),),
            )
            existing = cursor.fetchone()
            if not existing:
                raise ValueError("project not found")
            before = _row_dict(existing, PROJECT_COLUMNS)
            cursor.execute(
                f"""
                SELECT {", ".join(TENANT_COLUMNS)}
                FROM tenants
                WHERE id = %s
                FOR UPDATE
                """,
                (_uuid(before["tenant_id"]),),
            )
            tenant_before = _row_dict(cursor.fetchone(), TENANT_COLUMNS)
            after_candidate = dict(before)
            if name is not None:
                after_candidate["name"] = name
            if target_brand is not None:
                after_candidate["target_brand"] = target_brand
            if category is not None:
                after_candidate["category"] = category
            if status is not None:
                after_candidate["status"] = status
            if tenant_name is not None:
                cursor.execute(
                    """
                    UPDATE tenants
                    SET name = %s
                    WHERE id = %s
                    """,
                    (tenant_name, _uuid(before["tenant_id"])),
                )
            cursor.execute(
                """
                UPDATE projects
                SET name = %s,
                    target_brand = %s,
                    category = %s,
                    status = %s
                WHERE id = %s
                """,
                (
                    after_candidate["name"],
                    after_candidate["target_brand"],
                    after_candidate["category"],
                    after_candidate["status"],
                    _uuid(project_id),
                ),
            )
            if target_brand is not None:
                cursor.execute(
                    """
                    UPDATE brand_entities
                    SET canonical_name = %s
                    WHERE project_id = %s
                    """,
                    (target_brand, _uuid(project_id)),
                )
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_COLUMNS)}
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            after = _row_dict(cursor.fetchone(), PROJECT_COLUMNS)
            cursor.execute(
                f"""
                SELECT {", ".join(TENANT_COLUMNS)}
                FROM tenants
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(before["tenant_id"]),),
            )
            tenant_after = _row_dict(cursor.fetchone(), TENANT_COLUMNS)
            changed_fields = tuple(
                field
                for field in ("name", "target_brand", "category", "status")
                if before.get(field) != after.get(field)
            )
            if tenant_before.get("name") != tenant_after.get("name"):
                changed_fields = (*changed_fields, "tenant_name")
            audit_event = build_audit_event(
                event_type="project_updated",
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="project",
                target_id=project_id,
                before={**before, "tenant": tenant_before},
                after={**after, "tenant": tenant_after},
                input_refs={"project_ids": [project_id], "changed_fields": list(changed_fields)},
                output_refs={"project_ids": [project_id], "status": [str(after.get("status"))]},
                method_version="runtime_project_update_v1",
                reason=update.reason.strip() if update.reason else "runtime_project_update",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            record = self._load_runtime_project(cursor=cursor, project=after)
        self.connection.commit()
        return record

    def apply_runtime_project_action(self, action_input: RuntimeProjectActionInput) -> RuntimeProject:
        project_id = action_input.project_id.strip()
        action = action_input.action.strip().lower()
        updated_by = action_input.updated_by.strip() or "runtime-console"
        if not project_id:
            raise ValueError("project_id is required")
        if action not in {"archive", "restore"}:
            raise ValueError("action must be archive or restore")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_COLUMNS)}
                FROM projects
                WHERE id = %s
                FOR UPDATE
                """,
                (_uuid(project_id),),
            )
            existing = cursor.fetchone()
            if not existing:
                raise ValueError("project not found")
            before = _row_dict(existing, PROJECT_COLUMNS)
            before_status = str(before.get("status") or "")
            if action == "archive":
                if before_status == "archived":
                    raise ValueError("project already archived")
                after_status = "archived"
                event_type = "project_archived"
                method_version = "runtime_project_archive_v1"
            else:
                if before_status != "archived":
                    raise ValueError("project is not archived")
                after_status = "paused"
                event_type = "project_restored"
                method_version = "runtime_project_restore_v1"
            cursor.execute(
                """
                UPDATE projects
                SET status = %s
                WHERE id = %s
                """,
                (after_status, _uuid(project_id)),
            )
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_COLUMNS)}
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            after = _row_dict(cursor.fetchone(), PROJECT_COLUMNS)
            audit_event = build_audit_event(
                event_type=event_type,
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="project",
                target_id=project_id,
                before=before,
                after=after,
                input_refs={
                    "project_ids": [project_id],
                    "action": [action],
                    "status_before": [before_status],
                    "status_after": [after_status],
                },
                output_refs={"project_ids": [project_id], "status": [after_status]},
                method_version=method_version,
                reason=action_input.reason.strip() if action_input.reason else f"runtime_project_{action}",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            record = self._load_runtime_project(cursor=cursor, project=after)
        self.connection.commit()
        return record

    def save_runtime_project_brand_entity(self, entity_input: RuntimeProjectBrandEntityInput) -> RuntimeProjectEntity:
        project_id = entity_input.project_id.strip()
        canonical_name = entity_input.canonical_name.strip()
        updated_by = entity_input.updated_by.strip() or "runtime-console"
        status = entity_input.status.strip().lower()
        if not project_id:
            raise ValueError("project_id is required")
        if not canonical_name:
            raise ValueError("canonical_name is required")
        if status not in {"active", "paused", "archived"}:
            raise ValueError("status must be active, paused, or archived")
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s FOR UPDATE", (_uuid(project_id),))
            if not cursor.fetchone():
                raise ValueError("project not found")
            cursor.execute(
                f"""
                SELECT {", ".join(BRAND_ENTITY_COLUMNS)}
                FROM brand_entities
                WHERE project_id = %s
                ORDER BY id DESC
                LIMIT 1
                FOR UPDATE
                """,
                (_uuid(project_id),),
            )
            before_row = cursor.fetchone()
            before = _row_dict(before_row, BRAND_ENTITY_COLUMNS) if before_row else None
            entity_id = str(before["id"]) if before else _stable_id("brand-entity", project_id, canonical_name)
            cursor.execute(
                """
                INSERT INTO brand_entities (
                  id, project_id, canonical_name, official_domains, parent_company, product_lines, status
                )
                VALUES (%s, %s, %s, %s::jsonb, %s, %s::jsonb, %s)
                ON CONFLICT (id) DO UPDATE SET
                  canonical_name = EXCLUDED.canonical_name,
                  official_domains = EXCLUDED.official_domains,
                  parent_company = EXCLUDED.parent_company,
                  product_lines = EXCLUDED.product_lines,
                  status = EXCLUDED.status
                """,
                (
                    _uuid(entity_id),
                    _uuid(project_id),
                    canonical_name,
                    json.dumps(list(entity_input.official_domains)),
                    entity_input.parent_company.strip() if entity_input.parent_company else None,
                    json.dumps(list(entity_input.product_lines)),
                    status,
                ),
            )
            cursor.execute(
                """
                UPDATE projects
                SET target_brand = %s
                WHERE id = %s
                """,
                (canonical_name, _uuid(project_id)),
            )
            cursor.execute(
                f"""
                SELECT {", ".join(BRAND_ENTITY_COLUMNS)}
                FROM brand_entities
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(entity_id),),
            )
            after = _row_dict(cursor.fetchone(), BRAND_ENTITY_COLUMNS)
            audit_event = build_audit_event(
                event_type="project_brand_entity_saved",
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="brand_entity",
                target_id=entity_id,
                before=before,
                after=after,
                input_refs={"project_ids": [project_id], "entity_ids": [entity_id]},
                output_refs={"project_ids": [project_id], "entity_ids": [entity_id], "status": [status]},
                method_version="runtime_project_brand_entity_v1",
                reason=entity_input.reason.strip() if entity_input.reason else "runtime_project_brand_entity_save",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        return RuntimeProjectEntity(entity=after, audit_events=(asdict(audit_event),))

    def save_runtime_project_competitor_entity(
        self, entity_input: RuntimeProjectCompetitorEntityInput
    ) -> RuntimeProjectEntity:
        project_id = entity_input.project_id.strip()
        competitor_id = entity_input.competitor_id.strip() if entity_input.competitor_id else None
        canonical_name = entity_input.canonical_name.strip()
        updated_by = entity_input.updated_by.strip() or "runtime-console"
        status = entity_input.status.strip().lower()
        if not project_id:
            raise ValueError("project_id is required")
        if not canonical_name:
            raise ValueError("canonical_name is required")
        if status not in {"active", "paused", "archived"}:
            raise ValueError("status must be active, paused, or archived")
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s FOR UPDATE", (_uuid(project_id),))
            if not cursor.fetchone():
                raise ValueError("project not found")
            before = None
            if competitor_id:
                cursor.execute(
                    f"""
                    SELECT {", ".join(COMPETITOR_ENTITY_COLUMNS)}
                    FROM competitor_entities
                    WHERE id = %s AND project_id = %s
                    FOR UPDATE
                    """,
                    (_uuid(competitor_id), _uuid(project_id)),
                )
                before_row = cursor.fetchone()
                if not before_row:
                    raise ValueError("competitor not found")
                before = _row_dict(before_row, COMPETITOR_ENTITY_COLUMNS)
            else:
                competitor_id = _stable_id("competitor-entity", project_id, canonical_name)
            cursor.execute(
                """
                INSERT INTO competitor_entities (
                  id, project_id, canonical_name, official_domains, parent_company, product_lines, status
                )
                VALUES (%s, %s, %s, %s::jsonb, %s, %s::jsonb, %s)
                ON CONFLICT (id) DO UPDATE SET
                  canonical_name = EXCLUDED.canonical_name,
                  official_domains = EXCLUDED.official_domains,
                  parent_company = EXCLUDED.parent_company,
                  product_lines = EXCLUDED.product_lines,
                  status = EXCLUDED.status
                """,
                (
                    _uuid(competitor_id),
                    _uuid(project_id),
                    canonical_name,
                    json.dumps(list(entity_input.official_domains)),
                    entity_input.parent_company.strip() if entity_input.parent_company else None,
                    json.dumps(list(entity_input.product_lines)),
                    status,
                ),
            )
            cursor.execute(
                """
                SELECT count(*)
                FROM competitor_entities
                WHERE project_id = %s AND status = ANY(%s)
                """,
                (_uuid(project_id), ["active", "paused"]),
            )
            count_row = cursor.fetchone()
            active_count = int(count_row[0] if not isinstance(count_row, dict) else count_row["count"])
            if active_count < 3 or active_count > 5:
                self.connection.rollback()
                raise ValueError("project must keep 3-5 active or paused competitors")
            cursor.execute(
                f"""
                SELECT {", ".join(COMPETITOR_ENTITY_COLUMNS)}
                FROM competitor_entities
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(competitor_id),),
            )
            after = _row_dict(cursor.fetchone(), COMPETITOR_ENTITY_COLUMNS)
            audit_event = build_audit_event(
                event_type="project_competitor_entity_saved",
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="competitor_entity",
                target_id=competitor_id,
                before=before,
                after=after,
                input_refs={"project_ids": [project_id], "entity_ids": [competitor_id]},
                output_refs={"project_ids": [project_id], "entity_ids": [competitor_id], "status": [status]},
                method_version="runtime_project_competitor_entity_v1",
                reason=entity_input.reason.strip()
                if entity_input.reason
                else "runtime_project_competitor_entity_save",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        return RuntimeProjectEntity(entity=after, audit_events=(asdict(audit_event),))

    def list_runtime_project_lifecycle_events(
        self,
        *,
        project_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeProjectLifecycleEventPage:
        project_id = project_id.strip()
        if not project_id:
            raise ValueError("project_id is required")
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        lifecycle_event_types = (
            "project_bootstrap_created",
            "project_updated",
            "project_archived",
            "project_restored",
        )
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM audit_events
                WHERE project_id = %s
                  AND target_type = 'project'
                  AND event_type = ANY(%s)
                """,
                (_uuid(project_id), list(lifecycle_event_types)),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE project_id = %s
                  AND target_type = 'project'
                  AND event_type = ANY(%s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (_uuid(project_id), list(lifecycle_event_types), limit, offset),
            )
            audit_rows = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        records: list[RuntimeProjectLifecycleEvent] = []
        for row in audit_rows:
            input_refs = row.get("input_refs") if isinstance(row.get("input_refs"), dict) else {}
            output_refs = row.get("output_refs") if isinstance(row.get("output_refs"), dict) else {}
            lifecycle_event = {
                "id": row.get("id"),
                "project_id": row.get("project_id"),
                "event_type": row.get("event_type"),
                "actor_type": row.get("actor_type"),
                "actor_id": row.get("actor_id"),
                "target_id": row.get("target_id"),
                "method_version": row.get("method_version"),
                "reason": row.get("reason"),
                "created_at": row.get("created_at"),
                "before_hash": row.get("before_hash"),
                "after_hash": row.get("after_hash"),
                "action": _first_ref(input_refs.get("action")),
                "status_before": _first_ref(input_refs.get("status_before")),
                "status_after": _first_ref(input_refs.get("status_after") or output_refs.get("status")),
                "changed_fields": input_refs.get("changed_fields") or [],
            }
            records.append(RuntimeProjectLifecycleEvent(lifecycle_event=lifecycle_event, audit_events=(row,)))
        return RuntimeProjectLifecycleEventPage(total_count=total_count, limit=limit, offset=offset, records=tuple(records))

    def export_runtime_project_lifecycle_events_csv(
        self,
        *,
        project_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeProjectLifecycleEventExport:
        page = self.list_runtime_project_lifecycle_events(project_id=project_id, limit=limit, offset=offset)
        content = _render_runtime_project_lifecycle_events_csv(page)
        return RuntimeProjectLifecycleEventExport(
            export_type="runtime_project_lifecycle_events_csv",
            filename="runtime-project-lifecycle-events.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            project_id=project_id.strip(),
            method_version="runtime_project_lifecycle_export_v1",
            total_count=page.total_count,
            row_count=len(page.records),
        )

    def list_runtime_audit_events(
        self,
        *,
        project_id: str,
        event_type: str | None = None,
        target_type: str | None = None,
        actor_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeAuditEventPage:
        project_id = project_id.strip()
        if not project_id:
            raise ValueError("project_id is required")
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters = ["project_id = %s"]
        params: list[object] = [_uuid(project_id)]
        normalized_event_type = event_type.strip() if event_type else None
        normalized_target_type = target_type.strip() if target_type else None
        normalized_actor_id = actor_id.strip() if actor_id else None
        if normalized_event_type:
            filters.append("event_type = %s")
            params.append(normalized_event_type)
        if normalized_target_type:
            filters.append("target_type = %s")
            params.append(normalized_target_type)
        if normalized_actor_id:
            filters.append("actor_id = %s")
            params.append(normalized_actor_id)
        where_clause = f"WHERE {' AND '.join(filters)}"
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM audit_events {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        page_filters = {
            "project_id": project_id,
            "event_type": normalized_event_type,
            "target_type": normalized_target_type,
            "actor_id": normalized_actor_id,
        }
        return RuntimeAuditEventPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            filters={key: value for key, value in page_filters.items() if value},
            records=tuple(RuntimeAuditEvent(audit_event=row) for row in rows),
        )

    def export_runtime_audit_events_csv(
        self,
        *,
        project_id: str,
        event_type: str | None = None,
        target_type: str | None = None,
        actor_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeAuditEventExport:
        page = self.list_runtime_audit_events(
            project_id=project_id,
            event_type=event_type,
            target_type=target_type,
            actor_id=actor_id,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_audit_events_csv(page)
        return RuntimeAuditEventExport(
            export_type="runtime_audit_events_csv",
            filename="runtime-audit-events.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters=page.filters,
            total_count=page.total_count,
            row_count=len(page.records),
            method_version="runtime_audit_events_export_v1",
        )

    def user_can_access_project(self, *, project_id: str, actor_id: str) -> bool:
        if not actor_id:
            return False
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM project_members
                WHERE project_id = %s AND user_id = %s
                LIMIT 1
                """,
                (_uuid(project_id), actor_id),
            )
            return cursor.fetchone() is not None

    def get_project_member_role(self, *, project_id: str, actor_id: str) -> str | None:
        if not actor_id:
            return None
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT role
                FROM project_members
                WHERE project_id = %s AND user_id = %s
                LIMIT 1
                """,
                (_uuid(project_id), actor_id),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return str(row["role"] if isinstance(row, dict) else row[0])

    def get_entity_project_id(self, *, entity_id: str, entity_kind: str) -> str | None:
        normalized_kind = entity_kind.strip().lower()
        if normalized_kind not in {"brand", "competitor"}:
            raise ValueError("entity_kind must be brand or competitor")
        table_name = "brand_entities" if normalized_kind == "brand" else "competitor_entities"
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT project_id
                FROM {table_name}
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(entity_id),),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return str(row["project_id"] if isinstance(row, dict) else row[0])

    def get_report_export_project_id(self, *, report_export_id: str) -> str | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT project_id
                FROM report_exports
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(report_export_id),),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return str(row["project_id"] if isinstance(row, dict) else row[0])

    def get_report_export_latest_management_status(self, *, report_export_id: str) -> str | None:
        report_export_id = report_export_id.strip()
        if not report_export_id:
            raise ValueError("report_export_id is required")
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT input_refs
                FROM audit_events
                WHERE target_type = %s AND target_id = %s
                  AND event_type = %s
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                ("report_export", report_export_id, "report_export_management_recorded"),
            )
            row = cursor.fetchone()
        if not row:
            return None
        input_refs = row["input_refs"] if isinstance(row, dict) else row[0]
        if not isinstance(input_refs, dict):
            return None
        status_refs = input_refs.get("status") or ()
        if isinstance(status_refs, str):
            return status_refs.strip().lower() or None
        for status in status_refs:
            normalized = str(status).strip().lower()
            if normalized:
                return normalized
        return None

    def get_report_export_job_project_id(self, *, job_id: str) -> str | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT project_id
                FROM report_export_jobs
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(job_id),),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return str(row["project_id"] if isinstance(row, dict) else row[0])

    def get_runtime_notification_project_id(self, *, notification_id: str) -> str | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT project_id
                FROM runtime_notifications
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(notification_id),),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return str(row["project_id"] if isinstance(row, dict) else row[0])

    def get_runtime_notification_delivery_project_id(self, *, delivery_id: str) -> str | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT project_id
                FROM runtime_notification_deliveries
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(delivery_id),),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return str(row["project_id"] if isinstance(row, dict) else row[0])

    def get_runtime_notification_email_feedback_project_id(self, *, feedback_event_id: str) -> str | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT project_id
                FROM runtime_notification_email_feedback_events
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(feedback_event_id),),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return str(row["project_id"] if isinstance(row, dict) else row[0])

    def list_runtime_project_members(
        self,
        *,
        project_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeProjectMemberPage:
        project_id = project_id.strip()
        if not project_id:
            raise ValueError("project_id is required")
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM project_members
                WHERE project_id = %s
                """,
                (_uuid(project_id),),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_MEMBER_COLUMNS)}
                FROM project_members
                WHERE project_id = %s
                ORDER BY
                  CASE role
                    WHEN 'owner' THEN 1
                    WHEN 'admin' THEN 2
                    WHEN 'analyst' THEN 3
                    WHEN 'viewer' THEN 4
                    ELSE 5
                  END,
                  user_id ASC
                LIMIT %s OFFSET %s
                """,
                (_uuid(project_id), limit, offset),
            )
            rows = _rows_dict(cursor.fetchall(), PROJECT_MEMBER_COLUMNS)
            records = tuple(self._load_runtime_project_member(cursor=cursor, member=row) for row in rows)
        return RuntimeProjectMemberPage(total_count=total_count, limit=limit, offset=offset, records=records)

    def export_runtime_project_members_csv(
        self,
        *,
        project_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        page = self.list_runtime_project_members(project_id=project_id, limit=limit, offset=offset)
        content = _render_runtime_project_members_csv(page)
        filters = {
            "project_id": project_id.strip(),
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_project_members_csv",
            filename="runtime-project-members.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters=filters,
            total_count=page.total_count,
            row_count=len(page.records),
        )

    def save_runtime_project_member(self, member: RuntimeProjectMemberInput) -> RuntimeProjectMember:
        project_id = member.project_id.strip()
        user_id = member.user_id.strip()
        role = member.role.strip().lower()
        updated_by = member.updated_by.strip() or "runtime-console"
        if not project_id:
            raise ValueError("project_id is required")
        if not user_id:
            raise ValueError("user_id is required")
        if role not in {"owner", "admin", "analyst", "viewer"}:
            raise ValueError("role must be owner, admin, analyst, or viewer")
        member_id = _stable_id("project-member", project_id, user_id)
        after = {
            "id": member_id,
            "project_id": project_id,
            "user_id": user_id,
            "role": role,
        }
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            if not cursor.fetchone():
                raise ValueError("project not found")
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_MEMBER_COLUMNS)}
                FROM project_members
                WHERE project_id = %s AND user_id = %s
                LIMIT 1
                """,
                (_uuid(project_id), user_id),
            )
            existing = cursor.fetchone()
            before = _row_dict(existing, PROJECT_MEMBER_COLUMNS) if existing else None
            if before and before.get("role") == "owner" and role != "owner":
                self._assert_not_last_project_owner(cursor=cursor, project_id=project_id, user_id=user_id)
            cursor.execute(
                """
                INSERT INTO project_members (id, project_id, user_id, role)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (project_id, user_id) DO UPDATE SET
                  role = EXCLUDED.role
                """,
                (_uuid(member_id), _uuid(project_id), user_id, role),
            )
            audit_event = build_audit_event(
                event_type="project_member_saved",
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="project_member",
                target_id=member_id,
                before=before,
                after=after,
                input_refs={"project_ids": [project_id], "user_ids": [user_id]},
                output_refs={"project_member_ids": [member_id]},
                method_version="project_member_v1",
                reason=member.reason.strip() if member.reason else "runtime_project_member_upsert",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_MEMBER_COLUMNS)}
                FROM project_members
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(member_id),),
            )
            saved_row = cursor.fetchone()
        self.connection.commit()
        return RuntimeProjectMember(
            member=_row_dict(saved_row, PROJECT_MEMBER_COLUMNS),
            audit_events=(asdict(audit_event),),
        )

    def list_runtime_project_member_invitations(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeProjectMemberInvitationPage:
        project_id = project_id.strip()
        normalized_status = status.strip().lower() if status else None
        if not project_id:
            raise ValueError("project_id is required")
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        params: list[object] = [_uuid(project_id)]
        filters = "project_id = %s"
        if normalized_status:
            filters += " AND status = %s"
            params.append(normalized_status)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*)
                FROM project_member_invitations
                WHERE {filters}
                """,
                tuple(params),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_MEMBER_INVITATION_COLUMNS)}
                FROM project_member_invitations
                WHERE {filters}
                ORDER BY
                  CASE status
                    WHEN 'pending' THEN 1
                    WHEN 'accepted' THEN 2
                    WHEN 'revoked' THEN 3
                    WHEN 'expired' THEN 4
                    ELSE 5
                  END,
                  created_at DESC,
                  email ASC
                LIMIT %s OFFSET %s
                """,
                tuple([*params, limit, offset]),
            )
            rows = _rows_dict(cursor.fetchall(), PROJECT_MEMBER_INVITATION_COLUMNS)
            records = tuple(
                self._load_runtime_project_member_invitation(cursor=cursor, invitation=row) for row in rows
            )
        return RuntimeProjectMemberInvitationPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def export_runtime_project_member_invitations_csv(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        page = self.list_runtime_project_member_invitations(
            project_id=project_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_project_member_invitations_csv(page)
        filters = {
            "project_id": project_id.strip(),
            "status": status.strip().lower() if status else None,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_project_member_invitations_csv",
            filename="runtime-project-member-invitations.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=page.total_count,
            row_count=len(page.records),
        )

    def create_runtime_project_member_invitation(
        self,
        invitation: RuntimeProjectMemberInvitationInput,
    ) -> RuntimeProjectMemberInvitation:
        project_id = invitation.project_id.strip()
        email = invitation.email.strip().lower()
        role = invitation.role.strip().lower()
        invited_by = invitation.invited_by.strip() or "runtime-console"
        if not project_id:
            raise ValueError("project_id is required")
        if not email or "@" not in email:
            raise ValueError("email is required")
        if role not in {"owner", "admin", "analyst", "viewer"}:
            raise ValueError("role must be owner, admin, analyst, or viewer")
        metadata = _json_compatible(invitation.metadata or {})
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        status = "pending"
        invite_token = f"geno-invite-{uuid4().hex}"
        invite_token_hash = hashlib.sha256(invite_token.encode("utf-8")).hexdigest()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            if not cursor.fetchone():
                raise ValueError("project not found")
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_MEMBER_INVITATION_COLUMNS)}
                FROM project_member_invitations
                WHERE project_id = %s AND email = %s AND role = %s AND status = %s
                LIMIT 1
                """,
                (_uuid(project_id), email, role, status),
            )
            existing = cursor.fetchone()
            before = _row_dict(existing, PROJECT_MEMBER_INVITATION_COLUMNS) if existing else None
            invitation_id = str(before["id"]) if before else str(uuid4())
            cursor.execute(
                """
                INSERT INTO project_member_invitations (
                  id, project_id, email, role, status, invite_token_hash, invited_by,
                  expires_at, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id, email, role, status) DO UPDATE SET
                  invite_token_hash = EXCLUDED.invite_token_hash,
                  invited_by = EXCLUDED.invited_by,
                  expires_at = EXCLUDED.expires_at,
                  metadata = EXCLUDED.metadata,
                  updated_at = now()
                """,
                (
                    _uuid(invitation_id),
                    _uuid(project_id),
                    email,
                    role,
                    status,
                    invite_token_hash,
                    invited_by,
                    _datetime(invitation.expires_at),
                    _json_payload(metadata),
                ),
            )
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_MEMBER_INVITATION_COLUMNS)}
                FROM project_member_invitations
                WHERE project_id = %s AND email = %s AND role = %s AND status = %s
                LIMIT 1
                """,
                (_uuid(project_id), email, role, status),
            )
            saved_row = cursor.fetchone()
            saved_invitation = _row_dict(saved_row, PROJECT_MEMBER_INVITATION_COLUMNS)
            invitation_id = str(saved_invitation["id"])
            audit_event = build_audit_event(
                event_type="project_member_invitation_created",
                project_id=project_id,
                actor_type="user",
                actor_id=invited_by,
                target_type="project_member_invitation",
                target_id=invitation_id,
                before=before,
                after=saved_invitation,
                input_refs={
                    "project_ids": [project_id],
                    "emails": [email],
                    "roles": [role],
                    "status": [status],
                },
                output_refs={
                    "project_member_invitation_ids": [invitation_id],
                    "invite_token_hashes": [invite_token_hash],
                    "expires_at": [invitation.expires_at.isoformat() if invitation.expires_at else None],
                },
                method_version="project_member_invitation_v1",
                reason=invitation.reason.strip() if invitation.reason else "runtime_project_member_invitation_create",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        saved_invitation["invite_token"] = invite_token
        return RuntimeProjectMemberInvitation(
            invitation=saved_invitation,
            audit_events=(asdict(audit_event),),
        )

    def apply_runtime_project_member_invitation_action(
        self,
        action_input: RuntimeProjectMemberInvitationActionInput,
    ) -> RuntimeProjectMemberInvitation:
        project_id = action_input.project_id.strip()
        invitation_id = action_input.invitation_id.strip()
        action = action_input.action.strip().lower()
        updated_by = action_input.updated_by.strip() or "runtime-console"
        if not project_id:
            raise ValueError("project_id is required")
        if not invitation_id:
            raise ValueError("invitation_id is required")
        if action not in {"revoke", "expire"}:
            raise ValueError("action must be revoke or expire")
        next_status = "revoked" if action == "revoke" else "expired"
        event_type = (
            "project_member_invitation_revoked"
            if action == "revoke"
            else "project_member_invitation_expired"
        )
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_MEMBER_INVITATION_COLUMNS)}
                FROM project_member_invitations
                WHERE project_id = %s AND id = %s
                FOR UPDATE
                """,
                (_uuid(project_id), _uuid(invitation_id)),
            )
            existing = cursor.fetchone()
            if not existing:
                raise ValueError("project member invitation not found")
            before = _row_dict(existing, PROJECT_MEMBER_INVITATION_COLUMNS)
            if before.get("status") != "pending":
                raise ValueError(f"cannot {action} invitation with status {before.get('status')}")
            if action == "revoke":
                cursor.execute(
                    """
                    UPDATE project_member_invitations
                    SET status = %s,
                        revoked_at = now(),
                        updated_at = now()
                    WHERE project_id = %s AND id = %s
                    """,
                    (next_status, _uuid(project_id), _uuid(invitation_id)),
                )
            else:
                cursor.execute(
                    """
                    UPDATE project_member_invitations
                    SET status = %s,
                        updated_at = now()
                    WHERE project_id = %s AND id = %s
                    """,
                    (next_status, _uuid(project_id), _uuid(invitation_id)),
                )
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_MEMBER_INVITATION_COLUMNS)}
                FROM project_member_invitations
                WHERE project_id = %s AND id = %s
                LIMIT 1
                """,
                (_uuid(project_id), _uuid(invitation_id)),
            )
            saved_row = cursor.fetchone()
            after = _row_dict(saved_row, PROJECT_MEMBER_INVITATION_COLUMNS)
            audit_event = build_audit_event(
                event_type=event_type,
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="project_member_invitation",
                target_id=invitation_id,
                before=before,
                after=after,
                input_refs={
                    "project_ids": [project_id],
                    "project_member_invitation_ids": [invitation_id],
                    "actions": [action],
                    "previous_status": [str(before.get("status"))],
                },
                output_refs={
                    "project_member_invitation_ids": [invitation_id],
                    "status": [next_status],
                },
                method_version="project_member_invitation_action_v1",
                reason=action_input.reason.strip()
                if action_input.reason
                else f"runtime_project_member_invitation_{action}",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        return RuntimeProjectMemberInvitation(
            invitation=after,
            audit_events=(asdict(audit_event),),
        )

    def accept_runtime_project_member_invitation(
        self,
        invitation_input: RuntimeProjectMemberInvitationAcceptInput,
    ) -> RuntimeProjectMemberInvitation:
        invitation_id = invitation_input.invitation_id.strip()
        invite_token = invitation_input.invite_token.strip()
        if not invitation_id:
            raise ValueError("invitation_id is required")
        if not invite_token:
            raise ValueError("invite_token is required")
        invite_token_hash = hashlib.sha256(invite_token.encode("utf-8")).hexdigest()
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_MEMBER_INVITATION_COLUMNS)}
                FROM project_member_invitations
                WHERE id = %s AND invite_token_hash = %s
                FOR UPDATE
                """,
                (_uuid(invitation_id), invite_token_hash),
            )
            existing = cursor.fetchone()
            if not existing:
                raise ValueError("project member invitation not found")
            before_invitation = _row_dict(existing, PROJECT_MEMBER_INVITATION_COLUMNS)
            if before_invitation.get("status") != "pending":
                raise ValueError(f"cannot accept invitation with status {before_invitation.get('status')}")
            expires_at = _coerce_datetime(before_invitation.get("expires_at"))
            if expires_at and expires_at <= datetime.now(UTC):
                raise ValueError("project member invitation expired")
            project_id = str(before_invitation["project_id"])
            email = str(before_invitation["email"]).strip().lower()
            role = str(before_invitation["role"]).strip().lower()
            accepted_by = (invitation_input.accepted_by or "").strip() or email
            member_id = _stable_id("project-member", project_id, email)
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_MEMBER_COLUMNS)}
                FROM project_members
                WHERE project_id = %s AND user_id = %s
                LIMIT 1
                """,
                (_uuid(project_id), email),
            )
            existing_member = cursor.fetchone()
            before_member = _row_dict(existing_member, PROJECT_MEMBER_COLUMNS) if existing_member else None
            cursor.execute(
                """
                SELECT
                  set_config(%s, %s, false),
                  set_config(%s, %s, false),
                  set_config(%s, %s, false)
                """,
                (
                    "geno.runtime_actor_id",
                    email,
                    "geno.runtime_project_id",
                    project_id,
                    "geno.runtime_invitation_token_hash",
                    invite_token_hash,
                ),
            )
            cursor.execute(
                """
                INSERT INTO project_members (id, project_id, user_id, role)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (project_id, user_id) DO UPDATE SET
                  role = EXCLUDED.role
                """,
                (_uuid(member_id), _uuid(project_id), email, role),
            )
            cursor.execute(
                """
                UPDATE project_member_invitations
                SET status = %s,
                    accepted_at = now(),
                    updated_at = now()
                WHERE id = %s
                """,
                ("accepted", _uuid(invitation_id)),
            )
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_MEMBER_COLUMNS)}
                FROM project_members
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(member_id),),
            )
            saved_member = _row_dict(cursor.fetchone(), PROJECT_MEMBER_COLUMNS)
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_MEMBER_INVITATION_COLUMNS)}
                FROM project_member_invitations
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(invitation_id),),
            )
            after_invitation = _row_dict(cursor.fetchone(), PROJECT_MEMBER_INVITATION_COLUMNS)
            member_audit_event = build_audit_event(
                event_type="project_member_saved",
                project_id=project_id,
                actor_type="user",
                actor_id=accepted_by,
                target_type="project_member",
                target_id=member_id,
                before=before_member,
                after=saved_member,
                input_refs={
                    "project_ids": [project_id],
                    "user_ids": [email],
                    "project_member_invitation_ids": [invitation_id],
                },
                output_refs={"project_member_ids": [member_id]},
                method_version="project_member_invitation_accept_v1",
                reason=invitation_input.reason.strip()
                if invitation_input.reason
                else "runtime_project_member_invitation_accept_member",
            )
            invitation_audit_event = build_audit_event(
                event_type="project_member_invitation_accepted",
                project_id=project_id,
                actor_type="user",
                actor_id=accepted_by,
                target_type="project_member_invitation",
                target_id=invitation_id,
                before=before_invitation,
                after=after_invitation,
                input_refs={
                    "project_ids": [project_id],
                    "emails": [email],
                    "roles": [role],
                    "project_member_invitation_ids": [invitation_id],
                },
                output_refs={
                    "project_member_invitation_ids": [invitation_id],
                    "project_member_ids": [member_id],
                    "status": ["accepted"],
                },
                method_version="project_member_invitation_accept_v1",
                reason=invitation_input.reason.strip()
                if invitation_input.reason
                else "runtime_project_member_invitation_accept",
            )
            self.save_audit_events((member_audit_event, invitation_audit_event), cursor=cursor)
        self.connection.commit()
        after_invitation["member"] = saved_member
        return RuntimeProjectMemberInvitation(
            invitation=after_invitation,
            audit_events=(asdict(member_audit_event), asdict(invitation_audit_event)),
        )

    def send_runtime_project_member_invitation_email(
        self,
        email_input: RuntimeProjectMemberInvitationEmailInput,
    ) -> RuntimeProjectMemberInvitation:
        project_id = email_input.project_id.strip()
        invitation_id = email_input.invitation_id.strip()
        invite_token = email_input.invite_token.strip()
        accept_base_url = email_input.accept_base_url.strip()
        sent_by = email_input.sent_by.strip() or "runtime-console"
        smtp_env_prefix = email_input.smtp_env_prefix.strip() or "GENO_NOTIFICATION_SMTP"
        if not project_id:
            raise ValueError("project_id is required")
        if not invitation_id:
            raise ValueError("invitation_id is required")
        if not invite_token:
            raise ValueError("invite_token is required")
        if not accept_base_url:
            raise ValueError("accept_base_url is required")
        parsed_base_url = urlparse(accept_base_url)
        if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
            raise ValueError("accept_base_url must be an http or https URL")
        invite_token_hash = hashlib.sha256(invite_token.encode("utf-8")).hexdigest()
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_MEMBER_INVITATION_COLUMNS)}
                FROM project_member_invitations
                WHERE project_id = %s AND id = %s AND invite_token_hash = %s
                FOR UPDATE
                """,
                (_uuid(project_id), _uuid(invitation_id), invite_token_hash),
            )
            existing = cursor.fetchone()
            if not existing:
                raise ValueError("project member invitation not found")
            invitation = _row_dict(existing, PROJECT_MEMBER_INVITATION_COLUMNS)
            if invitation.get("status") != "pending":
                raise ValueError(f"cannot email invitation with status {invitation.get('status')}")
            expires_at = _coerce_datetime(invitation.get("expires_at"))
            if expires_at and expires_at <= datetime.now(UTC):
                raise ValueError("project member invitation expired")
            project_id = str(invitation["project_id"])
            email = str(invitation["email"]).strip().lower()
            role = str(invitation["role"]).strip().lower()
            accept_url = f"{accept_base_url.rstrip('/')}?{urlencode({'invitation_id': invitation_id, 'invite_token': invite_token})}"
            accept_url_hash = hashlib.sha256(accept_url.encode("utf-8")).hexdigest()
            rendered_email = render_project_member_invitation_email(
                role=role,
                invitation_id=invitation_id,
                expires_at=expires_at.isoformat() if expires_at else "not set",
                accept_url=accept_url,
                subject=email_input.subject,
                message=email_input.message,
            )
            delivery_result = send_runtime_email_message(
                recipients=(email,),
                subject=rendered_email.subject,
                text=rendered_email.text,
                headers={
                    "X-GENO-Project-Id": project_id,
                    "X-GENO-Invitation-Id": invitation_id,
                    "X-GENO-Invitation-Token-Hash": invite_token_hash,
                    "X-GENO-Email-Template-Version": rendered_email.template_version,
                },
                smtp_env_prefix=smtp_env_prefix,
                email_sender=self.email_sender,
            )
            if not 200 <= delivery_result.response_status < 300:
                raise RuntimeError(f"project member invitation email returned SMTP status {delivery_result.response_status}")
            event_after = {
                "invitation_id": invitation_id,
                "project_id": project_id,
                "email": email,
                "role": role,
                "status": invitation.get("status"),
                "delivery_status": "sent",
                "response_status": delivery_result.response_status,
                "response_body_hash": delivery_result.response_body_hash,
                "accept_url_hash": accept_url_hash,
                "email_template_version": rendered_email.template_version,
                "email_template_hash": rendered_email.template_hash,
                "email_subject_hash": rendered_email.subject_hash,
                "email_body_hash": rendered_email.body_hash,
                "smtp_host": delivery_result.smtp_host,
                "smtp_port": delivery_result.smtp_port,
                "from_address": delivery_result.from_address,
            }
            audit_event = build_audit_event(
                event_type="project_member_invitation_email_sent",
                project_id=project_id,
                actor_type="user",
                actor_id=sent_by,
                target_type="project_member_invitation",
                target_id=invitation_id,
                before=invitation,
                after=event_after,
                input_refs={
                    "project_ids": [project_id],
                    "project_member_invitation_ids": [invitation_id],
                    "emails": [email],
                    "roles": [role],
                    "invite_token_hashes": [invite_token_hash],
                    "accept_url_hashes": [accept_url_hash],
                    "email_template_versions": [rendered_email.template_version],
                    "email_template_hashes": [rendered_email.template_hash],
                    "email_subject_hashes": [rendered_email.subject_hash],
                    "email_body_hashes": [rendered_email.body_hash],
                    "smtp_env_prefix": [smtp_env_prefix],
                },
                output_refs={
                    "project_member_invitation_ids": [invitation_id],
                    "delivery_status": ["sent"],
                    "response_status": [str(delivery_result.response_status)],
                    "response_body_hashes": [delivery_result.response_body_hash],
                    "email_template_versions": [rendered_email.template_version],
                    "email_template_hashes": [rendered_email.template_hash],
                    "email_subject_hashes": [rendered_email.subject_hash],
                    "email_body_hashes": [rendered_email.body_hash],
                },
                method_version="project_member_invitation_email_v1",
                reason=email_input.reason.strip()
                if email_input.reason
                else "runtime_project_member_invitation_email_sent",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE project_id = %s AND target_type = %s AND target_id = %s
                ORDER BY created_at DESC
                LIMIT 5
                """,
                (_uuid(project_id), "project_member_invitation", invitation_id),
            )
            audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        self.connection.commit()
        return RuntimeProjectMemberInvitation(invitation=invitation, audit_events=tuple(audit_events))

    def delete_runtime_project_member(self, member: RuntimeProjectMemberDeleteInput) -> RuntimeProjectMember:
        project_id = member.project_id.strip()
        user_id = member.user_id.strip()
        deleted_by = member.deleted_by.strip() or "runtime-console"
        if not project_id:
            raise ValueError("project_id is required")
        if not user_id:
            raise ValueError("user_id is required")
        member_id = _stable_id("project-member", project_id, user_id)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_MEMBER_COLUMNS)}
                FROM project_members
                WHERE project_id = %s AND user_id = %s
                LIMIT 1
                """,
                (_uuid(project_id), user_id),
            )
            existing = cursor.fetchone()
            if not existing:
                raise ValueError("project member not found")
            before = _row_dict(existing, PROJECT_MEMBER_COLUMNS)
            if before.get("role") == "owner":
                self._assert_not_last_project_owner(cursor=cursor, project_id=project_id, user_id=user_id)
            cursor.execute(
                """
                DELETE FROM project_members
                WHERE project_id = %s AND user_id = %s
                """,
                (_uuid(project_id), user_id),
            )
            audit_event = build_audit_event(
                event_type="project_member_deleted",
                project_id=project_id,
                actor_type="user",
                actor_id=deleted_by,
                target_type="project_member",
                target_id=member_id,
                before=before,
                after=None,
                input_refs={"project_ids": [project_id], "user_ids": [user_id]},
                output_refs={"project_member_ids": [member_id]},
                method_version="project_member_delete_v1",
                reason=member.reason.strip() if member.reason else "runtime_project_member_delete",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        return RuntimeProjectMember(member=before, audit_events=(asdict(audit_event),))

    def _assert_not_last_project_owner(self, *, cursor: DbCursor, project_id: str, user_id: str) -> None:
        cursor.execute(
            """
            SELECT count(*)
            FROM project_members
            WHERE project_id = %s AND role = %s AND user_id <> %s
            """,
            (_uuid(project_id), "owner", user_id),
        )
        row = cursor.fetchone()
        remaining_owner_count = int(row[0] if not isinstance(row, dict) else row["count"])
        if remaining_owner_count < 1:
            raise ValueError("cannot remove or downgrade the last project owner")

    def _load_runtime_project_member(self, *, cursor: DbCursor, member: dict[str, Any]) -> RuntimeProjectMember:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            """,
            (_uuid(member["project_id"]), "project_member", str(member["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeProjectMember(member=member, audit_events=audit_events)

    def _load_runtime_project_member_invitation(
        self,
        *,
        cursor: DbCursor,
        invitation: dict[str, Any],
    ) -> RuntimeProjectMemberInvitation:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            """,
            (_uuid(invitation["project_id"]), "project_member_invitation", str(invitation["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeProjectMemberInvitation(invitation=invitation, audit_events=audit_events)

    def _load_runtime_project(self, *, cursor: DbCursor, project: dict[str, Any]) -> RuntimeProject:
        cursor.execute(
            f"""
            SELECT {", ".join(TENANT_COLUMNS)}
            FROM tenants
            WHERE id = %s
            """,
            (_uuid(project["tenant_id"]),),
        )
        tenant = _row_dict(cursor.fetchone(), TENANT_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(BRAND_ENTITY_COLUMNS)}
            FROM brand_entities
            WHERE project_id = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (_uuid(project["id"]),),
        )
        brand_row = cursor.fetchone()
        cursor.execute(
            f"""
            SELECT {", ".join(COMPETITOR_ENTITY_COLUMNS)}
            FROM competitor_entities
            WHERE project_id = %s
            ORDER BY canonical_name ASC
            """,
            (_uuid(project["id"]),),
        )
        competitors = _rows_dict(cursor.fetchall(), COMPETITOR_ENTITY_COLUMNS)
        cursor.execute(
            """
            SELECT count(*)
            FROM prompt_questions
            WHERE project_id = %s
            """,
            (_uuid(project["id"]),),
        )
        prompt_count_row = cursor.fetchone()
        prompt_count = int(
            prompt_count_row[0] if not isinstance(prompt_count_row, dict) else prompt_count_row["count"]
        )
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            """,
            (_uuid(project["id"]), "project", str(project["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeProject(
            project=project,
            tenant=tenant,
            brand=_row_dict(brand_row, BRAND_ENTITY_COLUMNS) if brand_row else None,
            competitors=competitors,
            prompt_count=prompt_count,
            audit_events=audit_events,
        )

    def list_runtime_entity_aliases(
        self,
        *,
        project_id: str | None = None,
        entity_kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeEntityAliasPage:
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("entity.project_id = %s")
            params.append(_uuid(project_id))
        if entity_kind:
            filters.append("ea.entity_kind = %s")
            params.append(entity_kind)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*)
                FROM entity_aliases ea
                JOIN (
                  SELECT id, project_id, 'brand' AS entity_kind FROM brand_entities
                  UNION ALL
                  SELECT id, project_id, 'competitor' AS entity_kind FROM competitor_entities
                ) entity ON entity.id = ea.entity_id AND entity.entity_kind = ea.entity_kind
                {where_clause}
                """,
                tuple(params),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT
                  {", ".join(f"ea.{column}" for column in ENTITY_ALIAS_COLUMNS)},
                  entity.project_id,
                  entity.canonical_name,
                  entity.official_domains,
                  entity.parent_company,
                  entity.product_lines,
                  entity.status
                FROM entity_aliases ea
                JOIN (
                  SELECT id, project_id, 'brand' AS entity_kind, canonical_name, official_domains, parent_company, product_lines, status
                  FROM brand_entities
                  UNION ALL
                  SELECT id, project_id, 'competitor' AS entity_kind, canonical_name, official_domains, parent_company, product_lines, status
                  FROM competitor_entities
                ) entity ON entity.id = ea.entity_id AND entity.entity_kind = ea.entity_kind
                {where_clause}
                ORDER BY ea.created_at DESC, ea.id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = _rows_dict(cursor.fetchall(), ENTITY_ALIAS_JOIN_COLUMNS)
            records = tuple(self._load_runtime_entity_alias(cursor=cursor, row=row) for row in rows)
        return RuntimeEntityAliasPage(total_count=total_count, limit=limit, offset=offset, records=records)

    def get_confirmed_entity_alias_terms(self, project_id: str) -> dict[str, tuple[str, ...]]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ea.entity_id, ea.alias
                FROM entity_aliases ea
                JOIN (
                  SELECT id, project_id, 'brand' AS entity_kind FROM brand_entities
                  UNION ALL
                  SELECT id, project_id, 'competitor' AS entity_kind FROM competitor_entities
                ) entity ON entity.id = ea.entity_id AND entity.entity_kind = ea.entity_kind
                WHERE entity.project_id = %s
                ORDER BY ea.created_at ASC, ea.alias ASC
                """,
                (_uuid(project_id),),
            )
            rows = _rows_dict(cursor.fetchall(), ("entity_id", "alias"))
        aliases: dict[str, list[str]] = {}
        for row in rows:
            entity_id = str(row["entity_id"])
            alias = str(row["alias"]).strip()
            if not alias:
                continue
            aliases.setdefault(entity_id, [])
            if alias.lower() not in {item.lower() for item in aliases[entity_id]}:
                aliases[entity_id].append(alias)
        return {entity_id: tuple(items) for entity_id, items in aliases.items()}

    def list_runtime_entity_alias_candidates(
        self,
        *,
        project_id: str,
        entity_kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeEntityAliasCandidatePage:
        filters: list[str] = ["entity.project_id = %s"]
        params: list[object] = [_uuid(project_id)]
        if entity_kind:
            filters.append("entity.entity_kind = %s")
            params.append(entity_kind)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                  entity.id,
                  entity.project_id,
                  entity.entity_kind,
                  entity.canonical_name,
                  entity.official_domains,
                  entity.parent_company,
                  entity.product_lines,
                  entity.status
                FROM (
                  SELECT id, project_id, 'brand' AS entity_kind, canonical_name, official_domains, parent_company, product_lines, status
                  FROM brand_entities
                  UNION ALL
                  SELECT id, project_id, 'competitor' AS entity_kind, canonical_name, official_domains, parent_company, product_lines, status
                  FROM competitor_entities
                ) entity
                WHERE {" AND ".join(filters)}
                ORDER BY entity.entity_kind ASC, entity.canonical_name ASC
                """,
                tuple(params),
            )
            entities = _rows_dict(
                cursor.fetchall(),
                (
                    "id",
                    "project_id",
                    "entity_kind",
                    "canonical_name",
                    "official_domains",
                    "parent_company",
                    "product_lines",
                    "status",
                ),
            )
            cursor.execute(
                """
                SELECT ar.id AS answer_run_id, ra.answer_text
                FROM answer_runs ar
                JOIN raw_answers ra ON ra.answer_run_id = ar.id
                WHERE ar.project_id = %s
                ORDER BY ar.collected_at DESC, ra.created_at DESC
                LIMIT 500
                """,
                (_uuid(project_id),),
            )
            answer_text_rows = _rows_dict(cursor.fetchall(), ("answer_run_id", "answer_text"))
            cursor.execute(
                """
                SELECT ar.id AS answer_run_id, ac.url, ac.domain
                FROM answer_runs ar
                JOIN answer_citations ac ON ac.answer_run_id = ar.id
                WHERE ar.project_id = %s
                ORDER BY ar.collected_at DESC, ac.position ASC, ac.created_at ASC
                LIMIT 500
                """,
                (_uuid(project_id),),
            )
            citation_rows = _rows_dict(cursor.fetchall(), ("answer_run_id", "url", "domain"))
        confirmed_aliases = self.get_confirmed_entity_alias_terms(project_id)
        records: list[RuntimeEntityAliasCandidate] = []
        latest_reviews = self.get_entity_alias_candidate_reviews(project_id)
        for entity in entities:
            entity_id = str(entity["id"])
            confirmed = confirmed_aliases.get(entity_id, ())
            seen = {str(entity["canonical_name"]).lower(), *(alias.lower() for alias in confirmed)}
            candidates: list[dict[str, Any]] = []
            _append_alias_candidate(
                candidates,
                seen,
                entity=entity,
                alias=f"{entity['canonical_name']} Australia",
                alias_type="alias",
                source="canonical_name_market",
                confidence=0.72,
            )
            for domain in entity.get("official_domains") or ():
                host = _alias_host(str(domain))
                _append_alias_candidate(
                    candidates,
                    seen,
                    entity=entity,
                    alias=host,
                    alias_type="domain",
                    source="official_domain",
                    confidence=0.9,
                )
            for product_line in entity.get("product_lines") or ():
                _append_alias_candidate(
                    candidates,
                    seen,
                    entity=entity,
                    alias=str(product_line),
                    alias_type="product",
                    source="product_line",
                    confidence=0.68,
                )
            if entity.get("parent_company"):
                _append_alias_candidate(
                    candidates,
                    seen,
                    entity=entity,
                    alias=str(entity["parent_company"]),
                    alias_type="parent_company",
                    source="parent_company",
                    confidence=0.74,
                )
            text_evidence: dict[str, dict[str, Any]] = {}
            canonical_name = str(entity["canonical_name"])
            for row in answer_text_rows:
                answer_run_id = str(row.get("answer_run_id") or "")
                answer_text = str(row.get("answer_text") or "")
                for alias in _answer_text_alias_candidates(canonical_name=canonical_name, answer_text=answer_text):
                    evidence = text_evidence.setdefault(alias, {"answer_run_ids": [], "count": 0})
                    evidence["count"] += 1
                    if answer_run_id and answer_run_id not in evidence["answer_run_ids"]:
                        evidence["answer_run_ids"].append(answer_run_id)
            for alias, evidence in sorted(
                text_evidence.items(),
                key=lambda item: (-int(item[1]["count"]), item[0].lower()),
            ):
                is_market_alias = alias.lower().endswith((" australia", " au"))
                _append_alias_candidate(
                    candidates,
                    seen,
                    entity=entity,
                    alias=alias,
                    alias_type="alias",
                    source="evidence_answer_text",
                    confidence=0.8 if is_market_alias else 0.73,
                    reason="alias phrase found in stored answer text",
                    evidence_answer_run_ids=tuple(evidence["answer_run_ids"][:5]),
                    evidence_count=int(evidence["count"]),
                )
            citation_evidence: dict[str, dict[str, Any]] = {}
            for row in citation_rows:
                host = _alias_host(str(row.get("domain") or row.get("url") or ""))
                if not _citation_host_matches_entity(host=host, canonical_name=canonical_name):
                    continue
                evidence = citation_evidence.setdefault(host, {"answer_run_ids": [], "urls": [], "count": 0})
                evidence["count"] += 1
                answer_run_id = str(row.get("answer_run_id") or "")
                url = str(row.get("url") or "")
                if answer_run_id and answer_run_id not in evidence["answer_run_ids"]:
                    evidence["answer_run_ids"].append(answer_run_id)
                if url and url not in evidence["urls"]:
                    evidence["urls"].append(url)
            for host, evidence in sorted(
                citation_evidence.items(),
                key=lambda item: (-int(item[1]["count"]), item[0].lower()),
            ):
                _append_alias_candidate(
                    candidates,
                    seen,
                    entity=entity,
                    alias=host,
                    alias_type="domain",
                    source="evidence_citation_domain",
                    confidence=0.82,
                    reason="domain appears in stored answer citation evidence and matches the entity name",
                    evidence_answer_run_ids=tuple(evidence["answer_run_ids"][:5]),
                    evidence_urls=tuple(evidence["urls"][:5]),
                    evidence_count=int(evidence["count"]),
                )
            for candidate in candidates:
                records.append(
                    RuntimeEntityAliasCandidate(
                        candidate=candidate,
                        entity=entity,
                        confirmed_aliases=confirmed,
                    )
                )
        visible_records: list[RuntimeEntityAliasCandidate] = []
        for record in records:
            review = latest_reviews.get(str(record.candidate["id"]))
            if review:
                candidate = {**record.candidate, "latest_review": review}
                if str(review.get("decision") or "").lower() == "rejected":
                    continue
                visible_records.append(
                    RuntimeEntityAliasCandidate(
                        candidate=candidate,
                        entity=record.entity,
                        confirmed_aliases=record.confirmed_aliases,
                    )
                )
                continue
            visible_records.append(record)
        total_count = len(visible_records)
        return RuntimeEntityAliasCandidatePage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=tuple(visible_records[offset : offset + limit]),
        )

    def get_entity_alias_candidate_reviews(self, project_id: str) -> dict[str, dict[str, Any]]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)}
                FROM entity_alias_candidate_reviews
                WHERE project_id = %s
                ORDER BY updated_at DESC, created_at DESC
                """,
                (_uuid(project_id),),
            )
            rows = _rows_dict(cursor.fetchall(), ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)
        reviews: dict[str, dict[str, Any]] = {}
        for row in rows:
            candidate_id = str(row.get("candidate_id") or "")
            if candidate_id and candidate_id not in reviews:
                reviews[candidate_id] = row
        return reviews

    def list_entity_alias_candidate_reviews(
        self,
        *,
        project_id: str,
        decision: str | None = None,
        entity_kind: str | None = None,
        assigned_to: str | None = None,
        assignment_status: str | None = None,
        priority: str | None = None,
        due_before: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeEntityAliasCandidateReviewPage:
        filters = ["project_id = %s"]
        params: list[Any] = [_uuid(project_id)]
        if decision:
            filters.append("decision = %s")
            params.append(decision.strip().lower())
        if entity_kind:
            filters.append("entity_kind = %s")
            params.append(entity_kind.strip().lower())
        if assigned_to:
            filters.append("assigned_to = %s")
            params.append(assigned_to.strip())
        if assignment_status:
            filters.append("assignment_status = %s")
            params.append(assignment_status.strip().lower())
        if priority:
            filters.append("priority = %s")
            params.append(priority.strip().lower())
        if due_before:
            filters.append("due_at <= %s")
            params.append(due_before)
        where_clause = f"WHERE {' AND '.join(filters)}"
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*)
                FROM entity_alias_candidate_reviews
                {where_clause}
                """,
                tuple(params),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)}
                FROM entity_alias_candidate_reviews
                {where_clause}
                ORDER BY updated_at DESC, created_at DESC, candidate_id
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = _rows_dict(cursor.fetchall(), ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)
            records = tuple(
                RuntimeEntityAliasCandidateReview(
                    review=row,
                    audit_events=self._load_entity_alias_candidate_review_audit_events(
                        cursor=cursor,
                        project_id=str(row["project_id"]),
                        review_id=str(row["id"]),
                    ),
                )
                for row in rows
            )
        return RuntimeEntityAliasCandidateReviewPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def get_entity_alias_candidate_assignment_queue_stats(
        self,
        *,
        project_id: str,
        due_soon_before: datetime | None = None,
    ) -> RuntimeEntityAliasCandidateAssignmentQueueStats:
        generated_at = datetime.now(UTC)
        due_soon_cutoff = due_soon_before or generated_at + timedelta(days=7)
        active_statuses = ("assigned", "in_progress", "blocked", "escalated")
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT assignment_status, priority, due_at, assigned_to
                FROM entity_alias_candidate_reviews
                WHERE project_id = %s
                """,
                (_uuid(project_id),),
            )
            rows = _rows_dict(cursor.fetchall(), ("assignment_status", "priority", "due_at", "assigned_to"))
        status_counts: dict[str, int] = {}
        priority_counts: dict[str, int] = {}
        active_due_dates: list[datetime] = []
        future_due_dates: list[datetime] = []
        active_count = 0
        unassigned_count = 0
        overdue_count = 0
        due_soon_count = 0
        for row in rows:
            status = str(row.get("assignment_status") or "unassigned").strip().lower() or "unassigned"
            priority = str(row.get("priority") or "normal").strip().lower() or "normal"
            assigned_to = str(row.get("assigned_to") or "").strip()
            status_counts[status] = status_counts.get(status, 0) + 1
            priority_counts[priority] = priority_counts.get(priority, 0) + 1
            if status == "unassigned" or not assigned_to:
                unassigned_count += 1
            if status not in active_statuses:
                continue
            active_count += 1
            due_at = _coerce_datetime(row.get("due_at"))
            if due_at is None:
                continue
            active_due_dates.append(due_at)
            if due_at < generated_at:
                overdue_count += 1
            elif due_at <= due_soon_cutoff:
                due_soon_count += 1
                future_due_dates.append(due_at)
            else:
                future_due_dates.append(due_at)
        return RuntimeEntityAliasCandidateAssignmentQueueStats(
            project_id=project_id,
            generated_at=generated_at,
            method_version="entity_alias_assignment_queue_stats_v1",
            active_statuses=active_statuses,
            total_count=len(rows),
            active_count=active_count,
            unassigned_count=unassigned_count,
            overdue_count=overdue_count,
            due_soon_count=due_soon_count,
            status_counts=dict(sorted(status_counts.items())),
            priority_counts=dict(sorted(priority_counts.items())),
            oldest_due_at=min(active_due_dates) if active_due_dates else None,
            next_due_at=min(future_due_dates) if future_due_dates else None,
        )

    def get_entity_alias_assignment_workbench(
        self,
        *,
        project_id: str,
        reviewer_id: str | None = None,
        due_soon_before: datetime | None = None,
        limit: int = 25,
    ) -> RuntimeEntityAliasAssignmentWorkbench:
        generated_at = datetime.now(UTC)
        due_soon_cutoff = due_soon_before or generated_at + timedelta(days=7)
        active_statuses = ("assigned", "in_progress", "blocked", "escalated")
        normalized_reviewer_id = reviewer_id.strip() if reviewer_id else None
        if limit < 1:
            raise ValueError("limit must be at least 1")
        bounded_limit = min(limit, 200)
        filters = ["project_id = %s", "assignment_status = ANY(%s)"]
        params: list[Any] = [_uuid(project_id), list(active_statuses)]
        if normalized_reviewer_id:
            filters.append("assigned_to = %s")
            params.append(normalized_reviewer_id)
        where_clause = f"WHERE {' AND '.join(filters)}"
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT assignment_status, priority, due_at
                FROM entity_alias_candidate_reviews
                {where_clause}
                """,
                tuple(params),
            )
            summary_rows = _rows_dict(cursor.fetchall(), ("assignment_status", "priority", "due_at"))
            cursor.execute(
                f"""
                SELECT {", ".join(ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)}
                FROM entity_alias_candidate_reviews
                {where_clause}
                ORDER BY
                  CASE assignment_status
                    WHEN 'escalated' THEN 0
                    WHEN 'blocked' THEN 1
                    WHEN 'in_progress' THEN 2
                    WHEN 'assigned' THEN 3
                    ELSE 4
                  END,
                  CASE WHEN due_at IS NOT NULL AND due_at < now() THEN 0 ELSE 1 END,
                  CASE priority
                    WHEN 'urgent' THEN 0
                    WHEN 'high' THEN 1
                    WHEN 'normal' THEN 2
                    WHEN 'low' THEN 3
                    ELSE 4
                  END,
                  due_at NULLS LAST,
                  updated_at DESC,
                  candidate_id
                LIMIT %s
                """,
                (*params, bounded_limit),
            )
            rows = _rows_dict(cursor.fetchall(), ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)
            records = tuple(
                RuntimeEntityAliasCandidateReview(
                    review=row,
                    audit_events=self._load_entity_alias_candidate_review_audit_events(
                        cursor=cursor,
                        project_id=str(row["project_id"]),
                        review_id=str(row["id"]),
                    ),
                )
                for row in rows
            )
        status_counts: dict[str, int] = {}
        priority_counts: dict[str, int] = {}
        due_dates: list[datetime] = []
        future_due_dates: list[datetime] = []
        overdue_count = 0
        due_soon_count = 0
        escalated_count = 0
        blocked_count = 0
        for row in summary_rows:
            status = str(row.get("assignment_status") or "unassigned").strip().lower() or "unassigned"
            priority = str(row.get("priority") or "normal").strip().lower() or "normal"
            status_counts[status] = status_counts.get(status, 0) + 1
            priority_counts[priority] = priority_counts.get(priority, 0) + 1
            if status == "escalated":
                escalated_count += 1
            if status == "blocked":
                blocked_count += 1
            due_at = _coerce_datetime(row.get("due_at"))
            if due_at is None:
                continue
            due_dates.append(due_at)
            if due_at < generated_at:
                overdue_count += 1
            elif due_at <= due_soon_cutoff:
                due_soon_count += 1
                future_due_dates.append(due_at)
            else:
                future_due_dates.append(due_at)
        return RuntimeEntityAliasAssignmentWorkbench(
            project_id=project_id,
            reviewer_id=normalized_reviewer_id,
            generated_at=generated_at,
            method_version="entity_alias_assignment_workbench_v1",
            active_statuses=active_statuses,
            total_count=len(summary_rows),
            active_count=len(summary_rows),
            overdue_count=overdue_count,
            due_soon_count=due_soon_count,
            escalated_count=escalated_count,
            blocked_count=blocked_count,
            status_counts=dict(sorted(status_counts.items())),
            priority_counts=dict(sorted(priority_counts.items())),
            oldest_due_at=min(due_dates) if due_dates else None,
            next_due_at=min(future_due_dates) if future_due_dates else None,
            records=records,
        )

    def get_entity_alias_assignment_workload_summary(
        self,
        *,
        project_id: str,
        due_soon_before: datetime | None = None,
    ) -> RuntimeEntityAliasAssignmentWorkloadSummary:
        generated_at = datetime.now(UTC)
        due_soon_cutoff = due_soon_before or generated_at + timedelta(days=7)
        active_statuses = ("assigned", "in_progress", "blocked", "escalated")
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT assignment_status, priority, due_at, assigned_to
                FROM entity_alias_candidate_reviews
                WHERE project_id = %s AND assignment_status = ANY(%s)
                """,
                (_uuid(project_id), list(active_statuses)),
            )
            rows = _rows_dict(cursor.fetchall(), ("assignment_status", "priority", "due_at", "assigned_to"))
        reviewer_loads: dict[str, dict[str, Any]] = {}
        unassigned_count = 0
        overdue_count = 0
        due_soon_count = 0
        escalated_count = 0
        blocked_count = 0
        for row in rows:
            reviewer_id = str(row.get("assigned_to") or "").strip() or "unassigned"
            status = str(row.get("assignment_status") or "unassigned").strip().lower() or "unassigned"
            priority = str(row.get("priority") or "normal").strip().lower() or "normal"
            load = reviewer_loads.setdefault(
                reviewer_id,
                {
                    "reviewer_id": reviewer_id,
                    "active_count": 0,
                    "overdue_count": 0,
                    "due_soon_count": 0,
                    "escalated_count": 0,
                    "blocked_count": 0,
                    "urgent_count": 0,
                    "high_count": 0,
                    "oldest_due_at": None,
                    "next_due_at": None,
                    "status_counts": {},
                    "priority_counts": {},
                    "_due_dates": [],
                    "_future_due_dates": [],
                },
            )
            load["active_count"] += 1
            load["status_counts"][status] = load["status_counts"].get(status, 0) + 1
            load["priority_counts"][priority] = load["priority_counts"].get(priority, 0) + 1
            if reviewer_id == "unassigned":
                unassigned_count += 1
            if status == "escalated":
                load["escalated_count"] += 1
                escalated_count += 1
            if status == "blocked":
                load["blocked_count"] += 1
                blocked_count += 1
            if priority == "urgent":
                load["urgent_count"] += 1
            if priority == "high":
                load["high_count"] += 1
            due_at = _coerce_datetime(row.get("due_at"))
            if due_at is None:
                continue
            load["_due_dates"].append(due_at)
            if due_at < generated_at:
                load["overdue_count"] += 1
                overdue_count += 1
            else:
                load["_future_due_dates"].append(due_at)
                if due_at <= due_soon_cutoff:
                    load["due_soon_count"] += 1
                    due_soon_count += 1
        normalized_loads: list[dict[str, Any]] = []
        for load in reviewer_loads.values():
            due_dates = load.pop("_due_dates")
            future_due_dates = load.pop("_future_due_dates")
            load["oldest_due_at"] = min(due_dates) if due_dates else None
            load["next_due_at"] = min(future_due_dates) if future_due_dates else None
            load["status_counts"] = dict(sorted(load["status_counts"].items()))
            load["priority_counts"] = dict(sorted(load["priority_counts"].items()))
            normalized_loads.append(load)
        normalized_loads.sort(
            key=lambda load: (
                0 if load["reviewer_id"] == "unassigned" else 1,
                -int(load["escalated_count"]),
                -int(load["overdue_count"]),
                -int(load["urgent_count"]),
                -int(load["active_count"]),
                str(load["reviewer_id"]),
            )
        )
        reviewer_count = sum(1 for load in normalized_loads if load["reviewer_id"] != "unassigned")
        return RuntimeEntityAliasAssignmentWorkloadSummary(
            project_id=project_id,
            generated_at=generated_at,
            method_version="entity_alias_assignment_workload_v1",
            active_statuses=active_statuses,
            total_active_count=len(rows),
            unassigned_count=unassigned_count,
            reviewer_count=reviewer_count,
            overdue_count=overdue_count,
            due_soon_count=due_soon_count,
            escalated_count=escalated_count,
            blocked_count=blocked_count,
            reviewer_loads=tuple(normalized_loads),
        )

    def build_entity_alias_assignment_dispatch_plan(
        self,
        plan_input: EntityAliasAssignmentDispatchPlanInput,
    ) -> RuntimeEntityAliasAssignmentDispatchPlan:
        project_id = plan_input.project_id.strip()
        if not project_id:
            raise ValueError("project_id is required")
        include_statuses = tuple(
            dict.fromkeys(
                status.strip().lower()
                for status in (plan_input.include_statuses or ("unassigned", "escalated"))
                if status.strip()
            )
        )
        if not include_statuses:
            raise ValueError("include_statuses are required")
        allowed_statuses = {"unassigned", "assigned", "in_progress", "blocked", "escalated"}
        invalid_statuses = [status for status in include_statuses if status not in allowed_statuses]
        if invalid_statuses:
            raise ValueError(f"unsupported include_statuses: {', '.join(invalid_statuses)}")
        max_per_reviewer = max(1, min(int(plan_input.max_per_reviewer or 10), 200))
        limit = max(1, min(int(plan_input.limit or 50), 200))
        strategy = plan_input.strategy.strip() or "least_loaded_round_robin"
        if strategy != "least_loaded_round_robin":
            raise ValueError("strategy must be least_loaded_round_robin")
        generated_at = datetime.now(UTC)
        workload = self.get_entity_alias_assignment_workload_summary(
            project_id=project_id,
            due_soon_before=plan_input.due_soon_before,
        )
        explicit_reviewer_ids = tuple(
            dict.fromkeys(reviewer.strip() for reviewer in plan_input.reviewer_ids if reviewer.strip())
        )
        inferred_reviewer_ids = tuple(
            str(load["reviewer_id"])
            for load in workload.reviewer_loads
            if str(load.get("reviewer_id") or "") != "unassigned"
        )
        reviewer_ids = explicit_reviewer_ids or inferred_reviewer_ids
        reviewer_loads: dict[str, dict[str, Any]] = {}
        workload_by_reviewer = {str(load["reviewer_id"]): load for load in workload.reviewer_loads}
        for reviewer_id in reviewer_ids:
            current_load = workload_by_reviewer.get(reviewer_id, {})
            active_count = int(current_load.get("active_count") or 0)
            reviewer_loads[reviewer_id] = {
                "reviewer_id": reviewer_id,
                "current_active_count": active_count,
                "planned_assignment_count": 0,
                "planned_active_count": active_count,
                "capacity_remaining": max(0, max_per_reviewer - active_count),
                "over_capacity": active_count >= max_per_reviewer,
                "status_counts": dict(current_load.get("status_counts") or {}),
                "priority_counts": dict(current_load.get("priority_counts") or {}),
                "next_due_at": current_load.get("next_due_at"),
            }
        filters = ["project_id = %s"]
        params: list[Any] = [_uuid(project_id)]
        status_filters: list[str] = []
        if "unassigned" in include_statuses:
            status_filters.append("(assignment_status = 'unassigned' OR assigned_to IS NULL OR assigned_to = '')")
        concrete_statuses = [status for status in include_statuses if status != "unassigned"]
        if concrete_statuses:
            status_filters.append("assignment_status = ANY(%s)")
            params.append(concrete_statuses)
        filters.append(f"({' OR '.join(status_filters)})")
        where_clause = f"WHERE {' AND '.join(filters)}"
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)}
                FROM entity_alias_candidate_reviews
                {where_clause}
                ORDER BY
                  CASE assignment_status
                    WHEN 'escalated' THEN 0
                    WHEN 'blocked' THEN 1
                    WHEN 'unassigned' THEN 2
                    WHEN 'assigned' THEN 3
                    WHEN 'in_progress' THEN 4
                    ELSE 5
                  END,
                  CASE WHEN due_at IS NOT NULL AND due_at < now() THEN 0 ELSE 1 END,
                  CASE priority
                    WHEN 'urgent' THEN 0
                    WHEN 'high' THEN 1
                    WHEN 'normal' THEN 2
                    WHEN 'low' THEN 3
                    ELSE 4
                  END,
                  due_at NULLS LAST,
                  updated_at DESC,
                  candidate_id
                LIMIT %s
                """,
                (*params, limit),
            )
            candidates = _rows_dict(cursor.fetchall(), ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)
        proposed_assignments: list[dict[str, Any]] = []
        skipped_candidates: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidates):
            if not reviewer_loads:
                skipped_candidates.append(
                    {
                        "candidate_id": candidate.get("candidate_id"),
                        "assignment_status": candidate.get("assignment_status"),
                        "reason": "no eligible reviewers",
                    }
                )
                continue
            available_loads = [
                load for load in reviewer_loads.values() if int(load["capacity_remaining"]) > 0
            ]
            if not available_loads:
                skipped_candidates.append(
                    {
                        "candidate_id": candidate.get("candidate_id"),
                        "assignment_status": candidate.get("assignment_status"),
                        "reason": "reviewer capacity exhausted",
                    }
                )
                continue
            selected_load = sorted(
                available_loads,
                key=lambda load: (
                    int(load["planned_active_count"]),
                    int(load["planned_assignment_count"]),
                    str(load["reviewer_id"]),
                ),
            )[0]
            selected_load["planned_assignment_count"] += 1
            selected_load["planned_active_count"] += 1
            selected_load["capacity_remaining"] = max(0, int(selected_load["capacity_remaining"]) - 1)
            proposed_assignments.append(
                {
                    "order": len(proposed_assignments) + 1,
                    "source_index": index,
                    "review_id": str(candidate.get("id") or ""),
                    "candidate_id": str(candidate.get("candidate_id") or ""),
                    "alias": candidate.get("alias"),
                    "entity_kind": candidate.get("entity_kind"),
                    "current_assigned_to": candidate.get("assigned_to"),
                    "current_assignment_status": candidate.get("assignment_status"),
                    "priority": candidate.get("priority"),
                    "due_at": candidate.get("due_at"),
                    "recommended_assigned_to": selected_load["reviewer_id"],
                    "recommended_assignment_status": "assigned",
                    "reason": "least loaded eligible reviewer within capacity",
                }
            )
        normalized_reviewer_loads = tuple(
            sorted(
                reviewer_loads.values(),
                key=lambda load: (
                    -int(load["planned_assignment_count"]),
                    int(load["planned_active_count"]),
                    str(load["reviewer_id"]),
                ),
            )
        )
        return RuntimeEntityAliasAssignmentDispatchPlan(
            project_id=project_id,
            generated_at=generated_at,
            method_version="entity_alias_assignment_dispatch_plan_v1",
            dry_run=True,
            strategy=strategy,
            include_statuses=include_statuses,
            reviewer_ids=reviewer_ids,
            active_statuses=workload.active_statuses,
            max_per_reviewer=max_per_reviewer,
            candidate_count=len(candidates),
            planned_assignment_count=len(proposed_assignments),
            skipped_count=len(skipped_candidates),
            reviewer_loads=normalized_reviewer_loads,
            proposed_assignments=tuple(proposed_assignments),
            skipped_candidates=tuple(skipped_candidates),
            source_summary={
                "workload_method_version": workload.method_version,
                "workload_generated_at": workload.generated_at,
                "workload_total_active_count": workload.total_active_count,
                "workload_unassigned_count": workload.unassigned_count,
                "workload_reviewer_count": workload.reviewer_count,
                "dry_run_does_not_write_assignment_state": True,
            },
        )

    def apply_entity_alias_assignment_dispatch_plan(
        self,
        apply_input: EntityAliasAssignmentDispatchApplyInput,
    ) -> RuntimeEntityAliasAssignmentDispatchApplyResult:
        project_id = apply_input.project_id.strip()
        applied_by = apply_input.applied_by.strip() or "runtime-console"
        assignment_status = apply_input.assignment_status.strip().lower() or "assigned"
        priority = apply_input.priority.strip().lower() if apply_input.priority else None
        assignment_note = apply_input.assignment_note.strip() if apply_input.assignment_note else None
        reason = apply_input.reason.strip() if apply_input.reason else assignment_note
        if not project_id:
            raise ValueError("project_id is required")
        if assignment_status not in {"assigned", "in_progress", "blocked", "escalated"}:
            raise ValueError("assignment_status must be assigned, in_progress, blocked, or escalated")
        if priority and priority not in {"low", "normal", "high", "urgent"}:
            raise ValueError("priority must be low, normal, high, or urgent")
        plan = self.build_entity_alias_assignment_dispatch_plan(
            EntityAliasAssignmentDispatchPlanInput(
                project_id=project_id,
                reviewer_ids=apply_input.reviewer_ids,
                include_statuses=apply_input.include_statuses,
                max_per_reviewer=apply_input.max_per_reviewer,
                due_soon_before=apply_input.due_soon_before,
                limit=apply_input.limit,
            )
        )
        proposals = tuple(plan.proposed_assignments)
        records: list[RuntimeEntityAliasCandidateReview] = []
        errors: list[dict[str, Any]] = []
        applied_audit_events: list[AuditEvent] = []
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s LIMIT 1", (_uuid(project_id),))
            if not cursor.fetchone():
                raise ValueError("project not found")
            for index, proposal in enumerate(proposals):
                candidate_id = str(proposal.get("candidate_id") or "").strip()
                assigned_to = str(proposal.get("recommended_assigned_to") or "").strip()
                try:
                    if not candidate_id:
                        raise ValueError("candidate_id is required")
                    if not assigned_to:
                        raise ValueError("recommended_assigned_to is required")
                    before = self._get_entity_alias_candidate_review_for_update(
                        cursor=cursor,
                        project_id=project_id,
                        candidate_id=candidate_id,
                        lock=True,
                    )
                    if not before:
                        raise ValueError("entity alias candidate review not found")
                    self._validate_dispatch_apply_candidate_status(
                        before=before,
                        include_statuses=plan.include_statuses,
                    )
                    effective_priority = priority or str(before.get("priority") or "normal").strip().lower() or "normal"
                    if effective_priority not in {"low", "normal", "high", "urgent"}:
                        effective_priority = "normal"
                    effective_due_at = apply_input.due_at if apply_input.due_at is not None else before.get("due_at")
                    effective_note = assignment_note or f"Dispatch plan applied by {applied_by}"
                    cursor.execute(
                        """
                        UPDATE entity_alias_candidate_reviews
                        SET assigned_to = %s,
                            assigned_by = %s,
                            assignment_status = %s,
                            assignment_note = %s,
                            assigned_at = now(),
                            due_at = %s,
                            priority = %s,
                            updated_at = now()
                        WHERE project_id = %s AND candidate_id = %s
                        """,
                        (
                            assigned_to,
                            applied_by,
                            assignment_status,
                            effective_note,
                            effective_due_at,
                            effective_priority,
                            _uuid(project_id),
                            candidate_id,
                        ),
                    )
                    record = self._get_entity_alias_candidate_review_for_update(
                        cursor=cursor,
                        project_id=project_id,
                        candidate_id=candidate_id,
                        lock=False,
                    )
                    audit_event = build_audit_event(
                        event_type="entity_alias_candidate_assignment_dispatch_applied",
                        project_id=project_id,
                        actor_type="user",
                        actor_id=applied_by,
                        target_type="entity_alias_candidate_review",
                        target_id=str(record["id"]),
                        before=before,
                        after=record,
                        input_refs={
                            "candidate_id": candidate_id,
                            "dispatch_plan_method_version": plan.method_version,
                            "dispatch_strategy": plan.strategy,
                            "include_statuses": list(plan.include_statuses),
                            "max_per_reviewer": plan.max_per_reviewer,
                            "source_plan_order": proposal.get("order"),
                            "recommended_assigned_to": assigned_to,
                        },
                        output_refs={
                            "entity_alias_candidate_review_ids": [str(record["id"])],
                            "candidate_ids": [candidate_id],
                            "assigned_to": assigned_to,
                            "assignment_status": assignment_status,
                            "priority": effective_priority,
                            "due_at": record.get("due_at"),
                        },
                        method_version="entity_alias_assignment_dispatch_apply_v1",
                        reason=reason or f"apply entity alias assignment dispatch plan by {applied_by}",
                    )
                    self.save_audit_events((audit_event,), cursor=cursor)
                    applied_audit_events.append(audit_event)
                    audit_rows = self._load_entity_alias_candidate_review_audit_events(
                        cursor=cursor,
                        project_id=str(record["project_id"]),
                        review_id=str(record["id"]),
                    )
                    records.append(RuntimeEntityAliasCandidateReview(review=record, audit_events=audit_rows))
                except ValueError as exc:
                    errors.append({"index": index, "candidate_id": candidate_id, "error": str(exc)})
                    if not apply_input.continue_on_error:
                        raise
            audit_summary = build_audit_event(
                event_type="entity_alias_assignment_dispatch_plan_applied",
                project_id=project_id,
                actor_type="user",
                actor_id=applied_by,
                target_type="entity_alias_assignment_dispatch_plan",
                target_id=_stable_id(
                    "entity-alias-assignment-dispatch-apply",
                    project_id,
                    applied_by,
                    *[str(proposal.get("candidate_id") or "") for proposal in proposals],
                ),
                before={"dispatch_plan": asdict(plan)},
                after={
                    "requested_count": len(proposals),
                    "applied_count": len(records),
                    "failed_count": len(errors),
                    "candidate_ids": [str(record.review["candidate_id"]) for record in records],
                    "failed_candidate_ids": [error["candidate_id"] for error in errors],
                },
                input_refs={
                    "dispatch_plan_method_version": plan.method_version,
                    "dispatch_strategy": plan.strategy,
                    "reviewer_ids": list(plan.reviewer_ids),
                    "include_statuses": list(plan.include_statuses),
                    "max_per_reviewer": plan.max_per_reviewer,
                    "limit": apply_input.limit,
                },
                output_refs={
                    "entity_alias_candidate_review_ids": [str(record.review["id"]) for record in records],
                    "candidate_ids": [str(record.review["candidate_id"]) for record in records],
                    "failed_candidate_ids": [error["candidate_id"] for error in errors],
                    "assignment_status": assignment_status,
                },
                method_version="entity_alias_assignment_dispatch_apply_v1",
                reason=reason or f"apply entity alias assignment dispatch plan by {applied_by}",
            )
            self.save_audit_events((audit_summary,), cursor=cursor)
        self.connection.commit()
        return RuntimeEntityAliasAssignmentDispatchApplyResult(
            project_id=project_id,
            method_version="entity_alias_assignment_dispatch_apply_v1",
            requested_count=len(proposals),
            applied_count=len(records),
            failed_count=len(errors),
            records=tuple(records),
            errors=tuple(errors),
            dispatch_plan=plan,
            audit_summary=asdict(audit_summary),
        )

    def _validate_dispatch_apply_candidate_status(
        self,
        *,
        before: dict[str, Any],
        include_statuses: tuple[str, ...],
    ) -> None:
        current_status = str(before.get("assignment_status") or "unassigned").strip().lower() or "unassigned"
        current_assigned_to = str(before.get("assigned_to") or "").strip()
        if current_status == "completed":
            raise ValueError("completed entity alias candidate review cannot be dispatch applied")
        status_matches = current_status in include_statuses
        unassigned_matches = "unassigned" in include_statuses and (not current_assigned_to or current_status == "unassigned")
        if not status_matches and not unassigned_matches:
            raise ValueError(
                f"entity alias candidate review status changed from dispatch plan eligibility: {current_status}"
            )

    def enqueue_entity_alias_assignment_overdue_notifications(
        self,
        *,
        project_id: str,
        assigned_to: str | None = None,
        priority: str | None = None,
        due_before: datetime | None = None,
        created_by: str = "runtime-console",
        reason: str | None = None,
    ) -> RuntimeEntityAliasAssignmentNotificationResult:
        project_id = project_id.strip()
        created_by = created_by.strip() or "runtime-console"
        normalized_assigned_to = assigned_to.strip() if assigned_to else None
        normalized_priority = priority.strip().lower() if priority else None
        cutoff = due_before or datetime.now(UTC)
        reason = reason.strip() if reason else "queue overdue entity alias assignment notifications"
        if not project_id:
            raise ValueError("project_id is required")
        active_statuses = ("assigned", "in_progress", "blocked")
        filters = [
            "project_id = %s",
            "assignment_status = ANY(%s)",
            "due_at IS NOT NULL",
            "due_at < %s",
        ]
        params: list[Any] = [_uuid(project_id), list(active_statuses), cutoff]
        if normalized_assigned_to:
            filters.append("assigned_to = %s")
            params.append(normalized_assigned_to)
        if normalized_priority:
            filters.append("priority = %s")
            params.append(normalized_priority)
        where_clause = f"WHERE {' AND '.join(filters)}"
        inserted_notifications: list[dict[str, Any]] = []
        audit_events: list[AuditEvent] = []
        delivery_count = 0
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s LIMIT 1", (_uuid(project_id),))
            if not cursor.fetchone():
                raise ValueError("project not found")
            cursor.execute(
                f"""
                SELECT {", ".join(ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)}
                FROM entity_alias_candidate_reviews
                {where_clause}
                ORDER BY due_at ASC, priority DESC, updated_at DESC, candidate_id
                LIMIT 200
                """,
                tuple(params),
            )
            reviews = _rows_dict(cursor.fetchall(), ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)
            for review in reviews:
                notification, events = self._insert_entity_alias_assignment_overdue_notification(
                    cursor=cursor,
                    review=review,
                    created_by=created_by,
                    reason=reason,
                )
                inserted_notifications.append(notification)
                audit_events.extend(events)
                delivery_count += sum(1 for event in events if event.event_type == "runtime_notification_delivery_queued")
            if audit_events:
                self.save_audit_events(tuple(audit_events), cursor=cursor)
        self.connection.commit()
        return RuntimeEntityAliasAssignmentNotificationResult(
            project_id=project_id,
            notification_count=len(inserted_notifications),
            delivery_count=delivery_count,
            skipped_count=0,
            notifications=tuple(inserted_notifications),
            audit_events=tuple(asdict(event) for event in audit_events),
        )

    def escalate_entity_alias_assignment_overdue_reviews(
        self,
        *,
        project_id: str,
        assigned_to: str | None = None,
        priority: str | None = None,
        due_before: datetime | None = None,
        escalated_by: str = "entity-alias-assignment-escalation-worker",
        reason: str | None = None,
    ) -> RuntimeEntityAliasAssignmentEscalationResult:
        project_id = project_id.strip()
        escalated_by = escalated_by.strip() or "entity-alias-assignment-escalation-worker"
        normalized_assigned_to = assigned_to.strip() if assigned_to else None
        normalized_priority = priority.strip().lower() if priority else None
        cutoff = due_before or datetime.now(UTC)
        reason = reason.strip() if reason else "escalate overdue entity alias assignment reviews"
        if not project_id:
            raise ValueError("project_id is required")
        active_statuses = ("assigned", "in_progress", "blocked")
        filters = [
            "project_id = %s",
            "assignment_status = ANY(%s)",
            "due_at IS NOT NULL",
            "due_at < %s",
        ]
        params: list[Any] = [_uuid(project_id), list(active_statuses), cutoff]
        if normalized_assigned_to:
            filters.append("assigned_to = %s")
            params.append(normalized_assigned_to)
        if normalized_priority:
            filters.append("priority = %s")
            params.append(normalized_priority)
        where_clause = f"WHERE {' AND '.join(filters)}"
        escalated_reviews: list[dict[str, Any]] = []
        audit_events: list[AuditEvent] = []
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s LIMIT 1", (_uuid(project_id),))
            if not cursor.fetchone():
                raise ValueError("project not found")
            cursor.execute(
                f"""
                SELECT {", ".join(ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)}
                FROM entity_alias_candidate_reviews
                {where_clause}
                ORDER BY due_at ASC, priority DESC, updated_at DESC, candidate_id
                LIMIT 200
                FOR UPDATE
                """,
                tuple(params),
            )
            reviews = _rows_dict(cursor.fetchall(), ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)
            for before in reviews:
                candidate_id = str(before.get("candidate_id") or "")
                review_id = str(before.get("id") or "")
                note = reason
                cursor.execute(
                    """
                    UPDATE entity_alias_candidate_reviews
                    SET assignment_status = 'escalated',
                        assignment_note = %s,
                        updated_at = now()
                    WHERE project_id = %s AND candidate_id = %s
                    """,
                    (note, _uuid(project_id), candidate_id),
                )
                record = self._get_entity_alias_candidate_review_for_update(
                    cursor=cursor,
                    project_id=project_id,
                    candidate_id=candidate_id,
                    lock=False,
                )
                audit_event = build_audit_event(
                    event_type="entity_alias_candidate_assignment_escalated",
                    project_id=project_id,
                    actor_type="worker",
                    actor_id=escalated_by,
                    target_type="entity_alias_candidate_review",
                    target_id=review_id,
                    before=before,
                    after=record,
                    input_refs={
                        "candidate_id": candidate_id,
                        "assigned_to": before.get("assigned_to"),
                        "priority": before.get("priority"),
                        "due_at": before.get("due_at"),
                    },
                    output_refs={
                        "entity_alias_candidate_review_ids": [review_id],
                        "candidate_ids": [candidate_id],
                        "assignment_status": "escalated",
                        "previous_assignment_status": before.get("assignment_status"),
                        "assigned_to": record.get("assigned_to"),
                        "priority": record.get("priority"),
                    },
                    method_version="entity_alias_candidate_assignment_escalation_v1",
                    reason=reason,
                )
                escalated_reviews.append(record)
                audit_events.append(audit_event)
            if audit_events:
                self.save_audit_events(tuple(audit_events), cursor=cursor)
        self.connection.commit()
        return RuntimeEntityAliasAssignmentEscalationResult(
            project_id=project_id,
            escalation_count=len(escalated_reviews),
            skipped_count=0,
            escalated_reviews=tuple(escalated_reviews),
            audit_events=tuple(asdict(event) for event in audit_events),
        )

    def _get_entity_alias_candidate_review_for_update(
        self,
        *,
        cursor: Any,
        project_id: str,
        candidate_id: str,
        lock: bool = False,
    ) -> dict[str, Any]:
        cursor.execute(
            f"""
            SELECT {", ".join(ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)}
            FROM entity_alias_candidate_reviews
            WHERE project_id = %s AND candidate_id = %s
            LIMIT 1
            {"FOR UPDATE" if lock else ""}
            """,
            (_uuid(project_id), candidate_id),
        )
        return _row_dict(cursor.fetchone(), ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)

    def reassign_entity_alias_candidate_reviews(
        self,
        reassignment: EntityAliasCandidateAssignmentReassignmentInput,
    ) -> RuntimeEntityAliasAssignmentReassignmentResult:
        project_id = reassignment.project_id.strip()
        assigned_to = reassignment.assigned_to.strip()
        reassigned_by = reassignment.reassigned_by.strip() or "runtime-console"
        from_assigned_to = reassignment.from_assigned_to.strip() if reassignment.from_assigned_to else None
        from_assignment_status = (
            reassignment.from_assignment_status.strip().lower() if reassignment.from_assignment_status else None
        )
        from_priority = reassignment.from_priority.strip().lower() if reassignment.from_priority else None
        assignment_status = reassignment.assignment_status.strip().lower() or "assigned"
        priority = reassignment.priority.strip().lower() or "high"
        assignment_note = reassignment.assignment_note.strip() if reassignment.assignment_note else None
        reason = (
            reassignment.reason.strip()
            if reassignment.reason
            else assignment_note or f"reassign entity alias candidate reviews to {assigned_to}"
        )
        limit = max(1, min(int(reassignment.limit or 50), 200))
        if not project_id:
            raise ValueError("project_id is required")
        if not assigned_to:
            raise ValueError("assigned_to is required")
        if assignment_status not in {"assigned", "in_progress", "blocked", "escalated"}:
            raise ValueError("assignment_status must be assigned, in_progress, blocked, or escalated")
        if priority not in {"low", "normal", "high", "urgent"}:
            raise ValueError("priority must be low, normal, high, or urgent")
        if from_assignment_status and from_assignment_status not in {"assigned", "in_progress", "blocked", "escalated"}:
            raise ValueError("from_assignment_status must be assigned, in_progress, blocked, or escalated")
        if from_priority and from_priority not in {"low", "normal", "high", "urgent"}:
            raise ValueError("from_priority must be low, normal, high, or urgent")
        if not any((from_assigned_to, from_assignment_status, from_priority, reassignment.due_before)):
            raise ValueError("at least one reassignment filter is required")
        filters = ["project_id = %s"]
        params: list[Any] = [_uuid(project_id)]
        if from_assigned_to:
            filters.append("assigned_to = %s")
            params.append(from_assigned_to)
        if from_assignment_status:
            filters.append("assignment_status = %s")
            params.append(from_assignment_status)
        if from_priority:
            filters.append("priority = %s")
            params.append(from_priority)
        if reassignment.due_before:
            filters.append("due_at IS NOT NULL")
            filters.append("due_at < %s")
            params.append(reassignment.due_before)
        where_clause = f"WHERE {' AND '.join(filters)}"
        reassigned_reviews: list[dict[str, Any]] = []
        audit_events: list[AuditEvent] = []
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s LIMIT 1", (_uuid(project_id),))
            if not cursor.fetchone():
                raise ValueError("project not found")
            cursor.execute(
                f"""
                SELECT {", ".join(ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)}
                FROM entity_alias_candidate_reviews
                {where_clause}
                ORDER BY
                    CASE assignment_status
                        WHEN 'escalated' THEN 0
                        WHEN 'blocked' THEN 1
                        WHEN 'in_progress' THEN 2
                        ELSE 3
                    END,
                    due_at ASC NULLS LAST,
                    priority DESC,
                    updated_at DESC,
                    candidate_id
                LIMIT %s
                FOR UPDATE
                """,
                (*params, limit),
            )
            reviews = _rows_dict(cursor.fetchall(), ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)
            for before in reviews:
                candidate_id = str(before.get("candidate_id") or "")
                review_id = str(before.get("id") or "")
                cursor.execute(
                    """
                    UPDATE entity_alias_candidate_reviews
                    SET assigned_to = %s,
                        assigned_by = %s,
                        assignment_status = %s,
                        assignment_note = %s,
                        assigned_at = now(),
                        due_at = %s,
                        priority = %s,
                        updated_at = now()
                    WHERE project_id = %s AND candidate_id = %s
                    """,
                    (
                        assigned_to,
                        reassigned_by,
                        assignment_status,
                        assignment_note,
                        reassignment.due_at,
                        priority,
                        _uuid(project_id),
                        candidate_id,
                    ),
                )
                record = self._get_entity_alias_candidate_review_for_update(
                    cursor=cursor,
                    project_id=project_id,
                    candidate_id=candidate_id,
                    lock=False,
                )
                audit_event = build_audit_event(
                    event_type="entity_alias_candidate_assignment_reassigned",
                    project_id=project_id,
                    actor_type="user",
                    actor_id=reassigned_by,
                    target_type="entity_alias_candidate_review",
                    target_id=review_id,
                    before=before,
                    after=record,
                    input_refs={
                        "candidate_id": candidate_id,
                        "previous_assigned_to": before.get("assigned_to"),
                        "previous_assignment_status": before.get("assignment_status"),
                        "previous_priority": before.get("priority"),
                    },
                    output_refs={
                        "entity_alias_candidate_review_ids": [review_id],
                        "candidate_ids": [candidate_id],
                        "assigned_to": assigned_to,
                        "assignment_status": assignment_status,
                        "priority": priority,
                    },
                    method_version="entity_alias_candidate_assignment_reassignment_v1",
                    reason=reason,
                )
                reassigned_reviews.append(record)
                audit_events.append(audit_event)
            if audit_events:
                self.save_audit_events(tuple(audit_events), cursor=cursor)
        self.connection.commit()
        return RuntimeEntityAliasAssignmentReassignmentResult(
            project_id=project_id,
            reassignment_count=len(reassigned_reviews),
            skipped_count=0,
            reassigned_reviews=tuple(reassigned_reviews),
            audit_events=tuple(asdict(event) for event in audit_events),
        )

    def assign_entity_alias_candidate_review(
        self,
        assignment: EntityAliasCandidateAssignmentInput,
    ) -> RuntimeEntityAliasCandidateReview:
        project_id = assignment.project_id.strip()
        candidate_id = assignment.candidate_id.strip()
        assigned_to = assignment.assigned_to.strip()
        assigned_by = assignment.assigned_by.strip() or "runtime-console"
        assignment_status = assignment.assignment_status.strip().lower() or "assigned"
        priority = assignment.priority.strip().lower() or "normal"
        assignment_note = assignment.assignment_note.strip() if assignment.assignment_note else None
        reason = assignment.reason.strip() if assignment.reason else None
        if not project_id:
            raise ValueError("project_id is required")
        if not candidate_id:
            raise ValueError("candidate_id is required")
        if not assigned_to:
            raise ValueError("assigned_to is required")
        if assignment_status not in {"assigned", "in_progress", "blocked", "escalated", "completed", "unassigned"}:
            raise ValueError(
                "assignment_status must be assigned, in_progress, blocked, escalated, completed, or unassigned"
            )
        if priority not in {"low", "normal", "high", "urgent"}:
            raise ValueError("priority must be low, normal, high, or urgent")
        with self.connection.cursor() as cursor:
            before = self._get_entity_alias_candidate_review_for_update(
                cursor=cursor,
                project_id=project_id,
                candidate_id=candidate_id,
                lock=False,
            )
            if not before:
                raise ValueError("entity alias candidate review not found")
            cursor.execute(
                """
                UPDATE entity_alias_candidate_reviews
                SET assigned_to = %s,
                    assigned_by = %s,
                    assignment_status = %s,
                    assignment_note = %s,
                    assigned_at = now(),
                    due_at = %s,
                    priority = %s,
                    updated_at = now()
                WHERE project_id = %s AND candidate_id = %s
                """,
                (
                    assigned_to,
                    assigned_by,
                    assignment_status,
                    assignment_note,
                    assignment.due_at,
                    priority,
                    _uuid(project_id),
                    candidate_id,
                ),
            )
            cursor.execute(
                f"""
                SELECT {", ".join(ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)}
                FROM entity_alias_candidate_reviews
                WHERE project_id = %s AND candidate_id = %s
                LIMIT 1
                """,
                (_uuid(project_id), candidate_id),
            )
            record = _row_dict(cursor.fetchone(), ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)
            audit_event = build_audit_event(
                event_type="entity_alias_candidate_assigned",
                project_id=project_id,
                actor_type="user",
                actor_id=assigned_by,
                target_type="entity_alias_candidate_review",
                target_id=str(record["id"]),
                before=before,
                after=record,
                input_refs={"candidate_id": candidate_id, "assigned_to": assigned_to},
                output_refs={
                    "entity_alias_candidate_review_ids": [str(record["id"])],
                    "assignment_status": assignment_status,
                    "priority": priority,
                    "due_at": record.get("due_at"),
                },
                method_version="entity_alias_candidate_assignment_v1",
                reason=reason or assignment_note or f"assign entity alias candidate review to {assigned_to}",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            audit_events = self._load_entity_alias_candidate_review_audit_events(
                cursor=cursor,
                project_id=str(record["project_id"]),
                review_id=str(record["id"]),
            )
        self.connection.commit()
        return RuntimeEntityAliasCandidateReview(review=record, audit_events=audit_events)

    def apply_entity_alias_candidate_assignment_action(
        self,
        action: EntityAliasCandidateAssignmentActionInput,
    ) -> RuntimeEntityAliasCandidateReview:
        project_id = action.project_id.strip()
        candidate_id = action.candidate_id.strip()
        action_name = action.action.strip().lower()
        updated_by = action.updated_by.strip() or "runtime-console"
        note = action.note.strip() if action.note else None
        if not project_id:
            raise ValueError("project_id is required")
        if not candidate_id:
            raise ValueError("candidate_id is required")
        if action_name not in {"claim", "release"}:
            raise ValueError("assignment action must be claim or release")
        with self.connection.cursor() as cursor:
            record, _audit_event = self._apply_entity_alias_candidate_assignment_action_locked(
                cursor=cursor,
                project_id=project_id,
                candidate_id=candidate_id,
                action_name=action_name,
                updated_by=updated_by,
                note=note,
                force=action.force,
            )
            audit_events = self._load_entity_alias_candidate_review_audit_events(
                cursor=cursor,
                project_id=str(record["project_id"]),
                review_id=str(record["id"]),
            )
        self.connection.commit()
        return RuntimeEntityAliasCandidateReview(review=record, audit_events=audit_events)

    def apply_entity_alias_candidate_assignment_batch_action(
        self,
        batch: EntityAliasCandidateAssignmentBatchActionInput,
    ) -> RuntimeEntityAliasAssignmentBatchActionResult:
        project_id = batch.project_id.strip()
        action_name = batch.action.strip().lower()
        updated_by = batch.updated_by.strip() or "runtime-console"
        note = batch.note.strip() if batch.note else None
        candidate_ids = tuple(dict.fromkeys(item.strip() for item in batch.candidate_ids if item.strip()))
        if not project_id:
            raise ValueError("project_id is required")
        if not candidate_ids:
            raise ValueError("candidate_ids are required")
        if len(candidate_ids) > 50:
            raise ValueError("candidate_ids can include at most 50 items")
        if action_name not in {"claim", "release"}:
            raise ValueError("assignment action must be claim or release")
        records: list[RuntimeEntityAliasCandidateReview] = []
        errors: list[dict[str, Any]] = []
        audit_events: list[AuditEvent] = []
        with self.connection.cursor() as cursor:
            for index, candidate_id in enumerate(candidate_ids):
                try:
                    record, audit_event = self._apply_entity_alias_candidate_assignment_action_locked(
                        cursor=cursor,
                        project_id=project_id,
                        candidate_id=candidate_id,
                        action_name=action_name,
                        updated_by=updated_by,
                        note=note,
                        force=batch.force,
                    )
                    audit_events.append(audit_event)
                    audit_rows = self._load_entity_alias_candidate_review_audit_events(
                        cursor=cursor,
                        project_id=str(record["project_id"]),
                        review_id=str(record["id"]),
                    )
                    records.append(RuntimeEntityAliasCandidateReview(review=record, audit_events=audit_rows))
                except ValueError as exc:
                    errors.append({"index": index, "candidate_id": candidate_id, "error": str(exc)})
                    if not batch.continue_on_error:
                        raise
            audit_summary = build_audit_event(
                event_type="entity_alias_candidate_assignment_batch_actioned",
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="entity_alias_candidate_review_batch",
                target_id=_stable_id("entity-alias-assignment-batch-action", project_id, action_name, *candidate_ids),
                before=None,
                after={
                    "action": action_name,
                    "requested_count": len(candidate_ids),
                    "actioned_count": len(records),
                    "failed_count": len(errors),
                    "candidate_ids": list(candidate_ids),
                },
                input_refs={"candidate_ids": list(candidate_ids), "assignment_action": action_name},
                output_refs={
                    "entity_alias_candidate_review_ids": [str(record.review["id"]) for record in records],
                    "candidate_ids": [str(record.review["candidate_id"]) for record in records],
                    "failed_candidate_ids": [error["candidate_id"] for error in errors],
                },
                method_version="entity_alias_candidate_assignment_batch_action_v1",
                reason=note or f"batch {action_name} entity alias candidate assignments by {updated_by}",
            )
            self.save_audit_events((audit_summary,), cursor=cursor)
        self.connection.commit()
        return RuntimeEntityAliasAssignmentBatchActionResult(
            project_id=project_id,
            action=action_name,
            requested_count=len(candidate_ids),
            actioned_count=len(records),
            failed_count=len(errors),
            records=tuple(records),
            errors=tuple(errors),
            audit_summary=asdict(audit_summary),
        )

    def _apply_entity_alias_candidate_assignment_action_locked(
        self,
        *,
        cursor: DbCursor,
        project_id: str,
        candidate_id: str,
        action_name: str,
        updated_by: str,
        note: str | None,
        force: bool,
    ) -> tuple[dict[str, Any], AuditEvent]:
        before = self._get_entity_alias_candidate_review_for_update(
            cursor=cursor,
            project_id=project_id,
            candidate_id=candidate_id,
            lock=True,
        )
        if not before:
            raise ValueError("entity alias candidate review not found")
        current_assignee = str(before.get("assigned_to") or "").strip()
        current_status = str(before.get("assignment_status") or "unassigned").strip().lower()
        if current_status == "completed":
            raise ValueError("completed entity alias candidate review cannot be claimed or released")
        if action_name == "claim":
            if current_assignee and current_assignee != updated_by and not force:
                raise ValueError("entity alias candidate review is already assigned")
            assigned_to: str | None = updated_by
            assigned_by: str | None = updated_by
            assignment_status = "in_progress" if current_status == "in_progress" else "assigned"
            assignment_note = note or before.get("assignment_note")
            assigned_at_sql = "COALESCE(assigned_at, now())"
            reason = note or f"claim entity alias candidate review by {updated_by}"
        else:
            if current_assignee and current_assignee != updated_by and not force:
                raise ValueError("entity alias candidate review is assigned to another reviewer")
            assigned_to = None
            assigned_by = updated_by
            assignment_status = "unassigned"
            assignment_note = note
            assigned_at_sql = "NULL"
            reason = note or f"release entity alias candidate review by {updated_by}"
        cursor.execute(
            f"""
            UPDATE entity_alias_candidate_reviews
            SET assigned_to = %s,
                assigned_by = %s,
                assignment_status = %s,
                assignment_note = %s,
                assigned_at = {assigned_at_sql},
                updated_at = now()
            WHERE project_id = %s AND candidate_id = %s
            """,
            (
                assigned_to,
                assigned_by,
                assignment_status,
                assignment_note,
                _uuid(project_id),
                candidate_id,
            ),
        )
        record = self._get_entity_alias_candidate_review_for_update(
            cursor=cursor,
            project_id=project_id,
            candidate_id=candidate_id,
            lock=False,
        )
        audit_event = build_audit_event(
            event_type="entity_alias_candidate_assignment_actioned",
            project_id=project_id,
            actor_type="user",
            actor_id=updated_by,
            target_type="entity_alias_candidate_review",
            target_id=str(record["id"]),
            before=before,
            after=record,
            input_refs={"candidate_id": candidate_id, "assignment_action": action_name},
            output_refs={
                "entity_alias_candidate_review_ids": [str(record["id"])],
                "assigned_to": record.get("assigned_to"),
                "assignment_status": record.get("assignment_status"),
            },
            method_version="entity_alias_candidate_assignment_action_v1",
            reason=reason,
        )
        self.save_audit_events((audit_event,), cursor=cursor)
        return record, audit_event

    def record_entity_alias_candidate_review(
        self,
        review: EntityAliasCandidateReviewInput,
    ) -> RuntimeEntityAliasCandidateReview:
        with self.connection.cursor() as cursor:
            self._validate_entity_alias_candidate_review(cursor=cursor, review=review)
            record, audit_event = self._upsert_entity_alias_candidate_review(cursor=cursor, review=review)
            audit_events = self._load_entity_alias_candidate_review_audit_events(
                cursor=cursor,
                project_id=str(record["project_id"]),
                review_id=str(record["id"]),
            )
        self.connection.commit()
        return RuntimeEntityAliasCandidateReview(review=record, audit_events=audit_events)

    def record_entity_alias_candidate_reviews(
        self,
        reviews: tuple[EntityAliasCandidateReviewInput, ...],
        *,
        reviewed_by: str = "runtime-console",
        notes: str | None = None,
        continue_on_error: bool = False,
    ) -> RuntimeEntityAliasCandidateBatchReviewResult:
        if not reviews:
            raise ValueError("at least one review is required")
        normalized_reviewer = reviewed_by.strip() or "runtime-console"
        batch_notes = notes.strip() if notes else None
        records: list[RuntimeEntityAliasCandidateReview] = []
        errors: list[dict[str, Any]] = []
        skipped_error_indexes: set[int] = set()
        validated_project_ids: set[str] = set()
        try:
            with self.connection.cursor() as cursor:
                for index, review in enumerate(reviews):
                    effective_review = self._with_entity_alias_candidate_batch_defaults(
                        review,
                        reviewed_by=normalized_reviewer,
                        notes=batch_notes,
                    )
                    try:
                        validated_project_ids.add(
                            self._validate_entity_alias_candidate_review(cursor=cursor, review=effective_review)
                        )
                    except ValueError as exc:
                        error = self._entity_alias_candidate_review_error(index=index, review=effective_review, error=str(exc))
                        if continue_on_error:
                            errors.append(error)
                            skipped_error_indexes.add(index)
                            continue
                        raise
                if len(validated_project_ids) > 1:
                    raise ValueError("reviews must belong to one project")
                for index, review in enumerate(reviews):
                    if index in skipped_error_indexes:
                        continue
                    effective_review = self._with_entity_alias_candidate_batch_defaults(
                        review,
                        reviewed_by=normalized_reviewer,
                        notes=batch_notes,
                    )
                    try:
                        record, audit_event = self._upsert_entity_alias_candidate_review(
                            cursor=cursor,
                            review=effective_review,
                        )
                        records.append(
                            RuntimeEntityAliasCandidateReview(
                                review=record,
                                audit_events=(asdict(audit_event),),
                            )
                        )
                    except ValueError as exc:
                        errors.append(self._entity_alias_candidate_review_error(index=index, review=effective_review, error=str(exc)))
                        if not continue_on_error:
                            raise
                decisions = sorted({str(record.review["decision"]) for record in records})
                review_ids = [str(record.review["id"]) for record in records]
                candidate_ids = [str(record.review["candidate_id"]) for record in records]
                entity_ids = [str(record.review["entity_id"]) for record in records]
                project_id = next(iter(validated_project_ids), "")
                audit_summary = {
                    "event_type": "entity_alias_candidate_batch_reviewed",
                    "method_version": "entity_alias_candidate_review_batch_v1",
                    "reviewed_by": normalized_reviewer,
                    "entity_alias_candidate_review_ids": review_ids,
                    "candidate_ids": candidate_ids,
                    "entity_ids": entity_ids,
                    "decisions": decisions,
                    "requested_count": len(reviews),
                    "reviewed_count": len(records),
                    "failed_count": len(errors),
                    "notes": batch_notes,
                    "individual_audit_event_type": "entity_alias_candidate_review_recorded",
                }
                if records and project_id:
                    batch_event = build_audit_event(
                        event_type="entity_alias_candidate_batch_reviewed",
                        project_id=project_id,
                        actor_type="user",
                        actor_id=normalized_reviewer,
                        target_type="entity_alias_candidate_review_batch",
                        target_id=str(uuid5(NAMESPACE_URL, "|".join(review_ids))),
                        before=None,
                        after=audit_summary,
                        input_refs={"candidate_ids": candidate_ids, "entity_ids": entity_ids},
                        output_refs={"entity_alias_candidate_review_ids": review_ids, "decisions": decisions},
                        method_version="entity_alias_candidate_review_batch_v1",
                        reason=batch_notes or "batch review generated entity alias candidates",
                    )
                    self.save_audit_events((batch_event,), cursor=cursor)
        except Exception:
            self.connection.rollback()
            raise
        self.connection.commit()
        return RuntimeEntityAliasCandidateBatchReviewResult(
            batch_version="entity_alias_candidate_review_batch_v1",
            requested_count=len(reviews),
            reviewed_count=len(records),
            failed_count=len(errors),
            records=tuple(records),
            errors=tuple(errors),
            audit_summary=audit_summary,
        )

    def _normalize_entity_alias_candidate_review(self, review: EntityAliasCandidateReviewInput) -> dict[str, Any]:
        project_id = review.project_id.strip()
        candidate_id = review.candidate_id.strip()
        entity_id = review.entity_id.strip()
        entity_kind = review.entity_kind.strip().lower()
        alias = review.alias.strip()
        alias_type = review.alias_type.strip().lower()
        decision = review.decision.strip().lower()
        reviewed_by = review.reviewed_by.strip() or "runtime-console"
        if not project_id:
            raise ValueError("project_id is required")
        if not candidate_id:
            raise ValueError("candidate_id is required")
        if not entity_id:
            raise ValueError("entity_id is required")
        if entity_kind not in {"brand", "competitor"}:
            raise ValueError("entity_kind must be brand or competitor")
        if not alias:
            raise ValueError("alias is required")
        if not alias_type:
            raise ValueError("alias_type is required")
        if decision not in {"needs_review", "rejected", "approved"}:
            raise ValueError("decision must be needs_review, rejected, or approved")
        confidence = None if review.confidence is None else max(0.0, min(1.0, float(review.confidence)))
        return {
            "id": _stable_id("entity-alias-candidate-review", project_id, candidate_id),
            "project_id": project_id,
            "candidate_id": candidate_id,
            "entity_id": entity_id,
            "entity_kind": entity_kind,
            "alias": alias,
            "alias_type": alias_type,
            "source": review.source.strip() if review.source else None,
            "confidence": confidence,
            "decision": decision,
            "reviewed_by": reviewed_by,
            "reason": review.reason.strip() if review.reason else None,
            "notes": review.notes.strip() if review.notes else None,
            "evidence_answer_run_ids": [item.strip() for item in review.evidence_answer_run_ids if item.strip()],
            "evidence_urls": [item.strip() for item in review.evidence_urls if item.strip()],
            "payload": review.payload or {},
        }

    def _validate_entity_alias_candidate_review(
        self,
        *,
        cursor: DbCursor,
        review: EntityAliasCandidateReviewInput,
    ) -> str:
        normalized = self._normalize_entity_alias_candidate_review(review)
        cursor.execute(
            """
            SELECT id
            FROM projects
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(normalized["project_id"]),),
        )
        if not cursor.fetchone():
            raise ValueError("project not found")
        cursor.execute(
            """
            SELECT id
            FROM (
              SELECT id, project_id, 'brand' AS entity_kind FROM brand_entities
              UNION ALL
              SELECT id, project_id, 'competitor' AS entity_kind FROM competitor_entities
            ) entity
            WHERE entity.id = %s AND entity.entity_kind = %s AND entity.project_id = %s
            LIMIT 1
            """,
            (_uuid(normalized["entity_id"]), normalized["entity_kind"], _uuid(normalized["project_id"])),
        )
        if not cursor.fetchone():
            raise ValueError("entity not found")
        return str(normalized["project_id"])

    def _upsert_entity_alias_candidate_review(
        self,
        *,
        cursor: DbCursor,
        review: EntityAliasCandidateReviewInput,
    ) -> tuple[dict[str, Any], AuditEvent]:
        normalized = self._normalize_entity_alias_candidate_review(review)
        cursor.execute(
            f"""
            SELECT {", ".join(ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)}
            FROM entity_alias_candidate_reviews
            WHERE project_id = %s AND candidate_id = %s
            LIMIT 1
            """,
            (_uuid(normalized["project_id"]), normalized["candidate_id"]),
        )
        before = _row_dict(cursor.fetchone(), ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)
        cursor.execute(
            """
            INSERT INTO entity_alias_candidate_reviews (
              id, project_id, candidate_id, entity_id, entity_kind, alias, alias_type,
              source, confidence, decision, reviewed_by, reason, notes,
              assignment_status, priority, evidence_answer_run_ids, evidence_urls, payload, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (project_id, candidate_id) DO UPDATE SET
              entity_id = EXCLUDED.entity_id,
              entity_kind = EXCLUDED.entity_kind,
              alias = EXCLUDED.alias,
              alias_type = EXCLUDED.alias_type,
              source = EXCLUDED.source,
              confidence = EXCLUDED.confidence,
              decision = EXCLUDED.decision,
              reviewed_by = EXCLUDED.reviewed_by,
              reason = EXCLUDED.reason,
              notes = EXCLUDED.notes,
              evidence_answer_run_ids = EXCLUDED.evidence_answer_run_ids,
              evidence_urls = EXCLUDED.evidence_urls,
              payload = EXCLUDED.payload,
              updated_at = now()
            """,
            (
                _uuid(normalized["id"]),
                _uuid(normalized["project_id"]),
                normalized["candidate_id"],
                _uuid(normalized["entity_id"]),
                normalized["entity_kind"],
                normalized["alias"],
                normalized["alias_type"],
                normalized["source"],
                normalized["confidence"],
                normalized["decision"],
                normalized["reviewed_by"],
                normalized["reason"],
                normalized["notes"],
                "unassigned",
                "normal",
                normalized["evidence_answer_run_ids"],
                normalized["evidence_urls"],
                _json_payload(normalized["payload"]),
            ),
        )
        cursor.execute(
            f"""
            SELECT {", ".join(ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)}
            FROM entity_alias_candidate_reviews
            WHERE project_id = %s AND candidate_id = %s
            LIMIT 1
            """,
            (_uuid(normalized["project_id"]), normalized["candidate_id"]),
        )
        record = _row_dict(cursor.fetchone(), ENTITY_ALIAS_CANDIDATE_REVIEW_COLUMNS)
        audit_event = build_audit_event(
            event_type="entity_alias_candidate_review_recorded",
            project_id=normalized["project_id"],
            actor_type="user",
            actor_id=normalized["reviewed_by"],
            target_type="entity_alias_candidate_review",
            target_id=str(record["id"]),
            before=before or None,
            after={**normalized, "id": str(record["id"])},
            input_refs={
                "candidate_id": normalized["candidate_id"],
                "entity_id": normalized["entity_id"],
                "evidence_answer_run_ids": normalized["evidence_answer_run_ids"],
                "evidence_urls": normalized["evidence_urls"],
            },
            output_refs={
                "entity_alias_candidate_review_ids": [str(record["id"])],
                "decision": normalized["decision"],
            },
            method_version="entity_alias_candidate_review_v1",
            reason=normalized["notes"] or f"record entity alias candidate review decision {normalized['decision']}",
        )
        self.save_audit_events((audit_event,), cursor=cursor)
        return record, audit_event

    def _load_entity_alias_candidate_review_audit_events(
        self,
        *,
        cursor: DbCursor,
        project_id: str,
        review_id: str,
    ) -> tuple[dict[str, Any], ...]:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (_uuid(project_id), "entity_alias_candidate_review", review_id),
        )
        return tuple(_rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS))

    def _with_entity_alias_candidate_batch_defaults(
        self,
        review: EntityAliasCandidateReviewInput,
        *,
        reviewed_by: str,
        notes: str | None,
    ) -> EntityAliasCandidateReviewInput:
        return EntityAliasCandidateReviewInput(
            project_id=review.project_id,
            candidate_id=review.candidate_id,
            entity_id=review.entity_id,
            entity_kind=review.entity_kind,
            alias=review.alias,
            alias_type=review.alias_type,
            decision=review.decision,
            reviewed_by=review.reviewed_by.strip() or reviewed_by,
            source=review.source,
            confidence=review.confidence,
            reason=review.reason,
            notes=review.notes if review.notes is not None else notes,
            evidence_answer_run_ids=review.evidence_answer_run_ids,
            evidence_urls=review.evidence_urls,
            payload=review.payload,
        )

    def _entity_alias_candidate_review_error(
        self,
        *,
        index: int,
        review: EntityAliasCandidateReviewInput,
        error: str,
    ) -> dict[str, Any]:
        return {
            "index": index,
            "project_id": review.project_id.strip(),
            "candidate_id": review.candidate_id.strip(),
            "entity_id": review.entity_id.strip(),
            "entity_kind": review.entity_kind.strip(),
            "alias": review.alias.strip(),
            "error": error,
        }

    def confirm_entity_alias(self, alias: EntityAliasInput) -> RuntimeEntityAlias:
        normalized_kind = alias.entity_kind.strip().lower()
        if normalized_kind not in {"brand", "competitor"}:
            raise ValueError("entity_kind must be brand or competitor")
        normalized_alias = alias.alias.strip()
        normalized_alias_type = alias.alias_type.strip().lower()
        if not normalized_alias:
            raise ValueError("alias is required")
        if not normalized_alias_type:
            raise ValueError("alias_type is required")
        confidence = max(0.0, min(1.0, float(alias.confidence)))
        table_name = "brand_entities" if normalized_kind == "brand" else "competitor_entities"
        alias_id = _stable_id("entity-alias", normalized_kind, alias.entity_id, normalized_alias, normalized_alias_type)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(BRAND_ENTITY_COLUMNS)}
                FROM {table_name}
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(alias.entity_id),),
            )
            entity = _row_dict(cursor.fetchone(), BRAND_ENTITY_COLUMNS)
            if not entity:
                raise ValueError("entity not found")
            cursor.execute(
                f"""
                SELECT {", ".join(ENTITY_ALIAS_COLUMNS)}
                FROM entity_aliases
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(alias_id),),
            )
            existing = cursor.fetchone()
            before = _row_dict(existing, ENTITY_ALIAS_COLUMNS) if existing else None
            after = {
                "id": alias_id,
                "entity_id": alias.entity_id,
                "entity_kind": normalized_kind,
                "alias": normalized_alias,
                "alias_type": normalized_alias_type,
                "confidence": confidence,
                "confirmed_by": alias.confirmed_by.strip() or "runtime-console",
                "notes": alias.notes,
            }
            cursor.execute(
                """
                INSERT INTO entity_aliases (
                  id, entity_id, entity_kind, alias, alias_type, confidence, confirmed_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  alias = EXCLUDED.alias,
                  alias_type = EXCLUDED.alias_type,
                  confidence = EXCLUDED.confidence,
                  confirmed_by = EXCLUDED.confirmed_by
                """,
                (
                    _uuid(alias_id),
                    _uuid(alias.entity_id),
                    normalized_kind,
                    normalized_alias,
                    normalized_alias_type,
                    confidence,
                    after["confirmed_by"],
                ),
            )
            audit_event = build_audit_event(
                event_type="entity_alias_confirmed",
                project_id=str(entity["project_id"]),
                actor_type="user",
                actor_id=str(after["confirmed_by"]),
                target_type="entity_alias",
                target_id=alias_id,
                before=before,
                after=after,
                input_refs={"entity_ids": [alias.entity_id]},
                output_refs={"entity_alias_ids": [alias_id]},
                method_version="entity_alias_confirm_v1",
                reason=alias.notes or "confirm entity alias for parser disambiguation",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            cursor.execute(
                f"""
                SELECT
                  {", ".join(f"ea.{column}" for column in ENTITY_ALIAS_COLUMNS)},
                  entity.project_id,
                  entity.canonical_name,
                  entity.official_domains,
                  entity.parent_company,
                  entity.product_lines,
                  entity.status
                FROM entity_aliases ea
                JOIN (
                  SELECT id, project_id, canonical_name, official_domains, parent_company, product_lines, status
                  FROM {table_name}
                ) entity ON entity.id = ea.entity_id
                WHERE ea.id = %s
                LIMIT 1
                """,
                (_uuid(alias_id),),
            )
            row = _row_dict(cursor.fetchone(), ENTITY_ALIAS_JOIN_COLUMNS)
            record = self._load_runtime_entity_alias(cursor=cursor, row=row)
        self.connection.commit()
        return record

    def _load_runtime_entity_alias(self, *, cursor: DbCursor, row: dict[str, Any]) -> RuntimeEntityAlias:
        entity_alias = {column: row[column] for column in ENTITY_ALIAS_COLUMNS if column in row}
        entity = {
            "id": row["entity_id"],
            "project_id": row["project_id"],
            "entity_kind": row["entity_kind"],
            "canonical_name": row["canonical_name"],
            "official_domains": row["official_domains"],
            "parent_company": row["parent_company"],
            "product_lines": row["product_lines"],
            "status": row["status"],
        }
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            """,
            (_uuid(entity["project_id"]), "entity_alias", str(entity_alias["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeEntityAlias(entity_alias=entity_alias, entity=entity, audit_events=audit_events)

    def list_runtime_prompts(
        self,
        *,
        project_id: str | None = None,
        market_code: str | None = None,
        intent_type: str | None = None,
        city: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> RuntimePromptPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if market_code:
            filters.append("market_code = %s")
            params.append(market_code)
        if intent_type:
            filters.append("intent_type = %s")
            params.append(intent_type)
        if city:
            filters.append("city = %s")
            params.append(city)
        if status:
            filters.append("status = %s")
            params.append(status)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*)
                FROM prompt_questions
                {where_clause}
                """,
                tuple(params),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(PROMPT_QUESTION_READ_COLUMNS)}
                FROM prompt_questions
                {where_clause}
                ORDER BY priority ASC, id ASC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            records = _rows_dict(cursor.fetchall(), PROMPT_QUESTION_READ_COLUMNS)
        return RuntimePromptPage(total_count=total_count, limit=limit, offset=offset, records=records)

    def export_runtime_prompts_csv(
        self,
        *,
        project_id: str | None = None,
        market_code: str | None = None,
        intent_type: str | None = None,
        city: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        normalized_project_id = project_id.strip() if project_id else None
        normalized_market_code = market_code.strip() if market_code else None
        normalized_intent_type = intent_type.strip() if intent_type else None
        normalized_city = city.strip() if city else None
        normalized_status = status.strip() if status else None
        page = self.list_runtime_prompts(
            project_id=normalized_project_id,
            market_code=normalized_market_code,
            intent_type=normalized_intent_type,
            city=normalized_city,
            status=normalized_status,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_prompts_csv(page)
        filters = {
            "project_id": normalized_project_id,
            "market_code": normalized_market_code,
            "intent_type": normalized_intent_type,
            "city": normalized_city,
            "status": normalized_status,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_prompts_csv",
            filename="runtime-prompts.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=page.total_count,
            row_count=len(page.records),
        )

    def get_runtime_prompt(self, prompt_question_id: str) -> dict[str, Any] | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(PROMPT_QUESTION_READ_COLUMNS)}
                FROM prompt_questions
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(prompt_question_id),),
            )
            row = cursor.fetchone()
        return _row_dict(row, PROMPT_QUESTION_READ_COLUMNS) if row else None

    def update_runtime_prompt(self, update: RuntimePromptUpdateInput) -> dict[str, Any]:
        project_id = update.project_id.strip()
        prompt_id = update.prompt_id.strip()
        updated_by = update.updated_by.strip() or "runtime-console"
        text = update.text.strip()
        intent_type = update.intent_type.strip()
        city = update.city.strip()
        language = update.language.strip()
        target_brand = update.target_brand.strip()
        competitors = tuple(item.strip() for item in update.competitors if item.strip())
        prompt_version = update.prompt_version.strip()
        status = update.status.strip().lower()
        if not project_id:
            raise ValueError("project_id is required")
        if not prompt_id:
            raise ValueError("prompt_id is required")
        if not text:
            raise ValueError("text is required")
        if not intent_type:
            raise ValueError("intent_type is required")
        if not city:
            raise ValueError("city is required")
        if not language:
            raise ValueError("language is required")
        if not target_brand:
            raise ValueError("target_brand is required")
        if not prompt_version:
            raise ValueError("prompt_version is required")
        if status not in {"active", "paused", "archived"}:
            raise ValueError("status must be active, paused, or archived")
        if update.priority < 0:
            raise ValueError("priority must be non-negative")
        if update.intent_weight <= 0:
            raise ValueError("intent_weight must be positive")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(PROMPT_QUESTION_READ_COLUMNS)}
                FROM prompt_questions
                WHERE id = %s AND project_id = %s
                FOR UPDATE
                """,
                (_uuid(prompt_id), _uuid(project_id)),
            )
            before_row = cursor.fetchone()
            if not before_row:
                raise ValueError("prompt not found")
            before = _row_dict(before_row, PROMPT_QUESTION_READ_COLUMNS)
            cursor.execute(
                """
                UPDATE prompt_questions
                SET text = %s,
                    intent_type = %s,
                    city = %s,
                    language = %s,
                    target_brand = %s,
                    competitors = %s,
                    priority = %s,
                    intent_weight = %s,
                    prompt_version = %s,
                    status = %s
                WHERE id = %s AND project_id = %s
                """,
                (
                    text,
                    intent_type,
                    city,
                    language,
                    target_brand,
                    _json_payload(competitors),
                    update.priority,
                    update.intent_weight,
                    prompt_version,
                    status,
                    _uuid(prompt_id),
                    _uuid(project_id),
                ),
            )
            cursor.execute(
                f"""
                SELECT {", ".join(PROMPT_QUESTION_READ_COLUMNS)}
                FROM prompt_questions
                WHERE id = %s AND project_id = %s
                LIMIT 1
                """,
                (_uuid(prompt_id), _uuid(project_id)),
            )
            after = _row_dict(cursor.fetchone(), PROMPT_QUESTION_READ_COLUMNS)
            changed_fields = tuple(
                field
                for field in (
                    "text",
                    "intent_type",
                    "city",
                    "language",
                    "target_brand",
                    "competitors",
                    "priority",
                    "intent_weight",
                    "prompt_version",
                    "status",
                )
                if before.get(field) != after.get(field)
            )
            audit_event = build_audit_event(
                event_type="runtime_prompt_updated",
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="prompt_question",
                target_id=prompt_id,
                before=before,
                after=after,
                input_refs={"prompt_question_ids": [prompt_id], "changed_fields": list(changed_fields)},
                output_refs={"prompt_question_ids": [prompt_id], "status": [str(after.get("status"))]},
                method_version="runtime_prompt_update_v1",
                reason=update.reason.strip() if update.reason else "runtime_prompt_update",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        return after

    def list_runtime_prompt_imports(
        self,
        *,
        project_id: str | None = None,
        source_format: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> RuntimePromptImportHistoryPage:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        filters = ["event_type = %s", "target_type = %s"]
        params: list[object] = ["runtime_prompts_imported", "prompt_import"]
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if source_format:
            filters.append("COALESCE(input_refs ->> 'source_format', 'csv') = %s")
            params.append(source_format.strip().lower())
        where_clause = f"WHERE {' AND '.join(filters)}"
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*)
                FROM audit_events
                {where_clause}
                """,
                tuple(params),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            audit_rows = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        records = tuple(RuntimePromptImportHistoryItem(prompt_import=_prompt_import_history(row), audit_events=(row,)) for row in audit_rows)
        return RuntimePromptImportHistoryPage(total_count=total_count, limit=limit, offset=offset, records=records)

    def import_runtime_prompts_csv(self, prompt_import: RuntimePromptImportInput) -> RuntimePromptImportResult:
        project_id = prompt_import.project_id.strip()
        imported_by = prompt_import.imported_by.strip() or "runtime-console"
        max_rows = max(1, min(prompt_import.max_rows, 200))
        source_format = (prompt_import.source_format or "csv").strip().lower()
        source_filename = (prompt_import.source_filename or "").strip() or None
        source_content_type = (prompt_import.source_content_type or "").strip() or None
        if not project_id:
            raise ValueError("project_id is required")
        prompts = _parse_prompt_import_csv(
            project_id=project_id,
            csv_content=prompt_import.csv_content,
            max_rows=max_rows,
        )
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, market_code, industry_code, target_brand, prompt_version
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            project_row = cursor.fetchone()
            if not project_row:
                raise ValueError("project not found")
            project = _row_dict(project_row, ("id", "market_code", "industry_code", "target_brand", "prompt_version"))
            cursor.execute(
                """
                SELECT canonical_name
                FROM competitor_entities
                WHERE project_id = %s
                ORDER BY canonical_name ASC
                """,
                (_uuid(project_id),),
            )
            competitor_rows = _rows_dict(cursor.fetchall(), ("canonical_name",))
            default_competitors = tuple(str(row["canonical_name"]) for row in competitor_rows)
            normalized_prompts = tuple(
                _normalize_import_prompt(
                    prompt=prompt,
                    project=project,
                    default_competitors=default_competitors,
                )
                for prompt in prompts
            )
            before = {"project_id": project_id, "imported_prompt_count": 0}
            prompt_ids: list[str] = []
            for index, prompt in enumerate(normalized_prompts, start=1):
                prompt_id = _stable_id("runtime-prompt-import", project_id, prompt["prompt_version"], index, prompt["text"])
                prompt_ids.append(prompt_id)
                cursor.execute(
                    """
                    INSERT INTO prompt_questions (
                      id, project_id, market_code, industry_code, text, intent_type, city,
                      language, target_brand, competitors, priority, intent_weight,
                      prompt_version, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      text = EXCLUDED.text,
                      intent_type = EXCLUDED.intent_type,
                      city = EXCLUDED.city,
                      language = EXCLUDED.language,
                      target_brand = EXCLUDED.target_brand,
                      competitors = EXCLUDED.competitors,
                      priority = EXCLUDED.priority,
                      intent_weight = EXCLUDED.intent_weight,
                      prompt_version = EXCLUDED.prompt_version,
                      status = EXCLUDED.status
                    """,
                    (
                        _uuid(prompt_id),
                        _uuid(project_id),
                        prompt["market_code"],
                        prompt["industry_code"],
                        prompt["text"],
                        prompt["intent_type"],
                        prompt["city"],
                        prompt["language"],
                        prompt["target_brand"],
                        _json_payload(prompt["competitors"]),
                        prompt["priority"],
                        prompt["intent_weight"],
                        prompt["prompt_version"],
                        prompt["status"],
                    ),
                )
            after = {
                "project_id": project_id,
                "prompt_count": len(normalized_prompts),
                "prompt_ids": prompt_ids,
                "prompt_version": normalized_prompts[0]["prompt_version"] if normalized_prompts else project["prompt_version"],
                "source_format": source_format,
                "source_filename": source_filename,
            }
            audit_event = build_audit_event(
                event_type="runtime_prompts_imported",
                project_id=project_id,
                actor_type="user",
                actor_id=imported_by,
                target_type="prompt_import",
                target_id=_stable_id("prompt-import", project_id, imported_by, len(normalized_prompts)),
                before=before,
                after=after,
                input_refs={
                    "csv_sha256": [_artifact_hash(prompt_import.csv_content)],
                    "source_format": source_format,
                    "source_filename": source_filename,
                    "source_content_type": source_content_type,
                },
                output_refs={"prompt_question_ids": prompt_ids},
                method_version=f"runtime_prompt_import_{source_format}_v1",
                reason=f"import runtime prompts from {source_format}",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            imported_rows: list[dict[str, Any]] = []
            for prompt_id in prompt_ids:
                cursor.execute(
                    f"""
                    SELECT {", ".join(PROMPT_QUESTION_READ_COLUMNS)}
                    FROM prompt_questions
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (_uuid(prompt_id),),
                )
                row = cursor.fetchone()
                if row:
                    imported_rows.append(_row_dict(row, PROMPT_QUESTION_READ_COLUMNS))
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE project_id = %s AND target_type = %s AND target_id = %s
                ORDER BY created_at DESC
                LIMIT 5
                """,
                (_uuid(project_id), "prompt_import", audit_event.target_id),
            )
            audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        self.connection.commit()
        return RuntimePromptImportResult(
            prompt_import=after,
            prompts=tuple(imported_rows),
            audit_events=audit_events,
        )

    def list_runtime_evidence_runs(
        self,
        *,
        project_id: str | None = None,
        platform: str | None = None,
        city: str | None = None,
        intent_type: str | None = None,
        status: str | None = None,
        sort: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeEvidencePage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        sort_key, order_by = _runtime_evidence_sort(sort)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("ar.project_id = %s")
            params.append(_uuid(project_id))
        if platform:
            filters.append("ar.platform = %s")
            params.append(platform)
        if city:
            filters.append("ar.city = %s")
            params.append(city)
        if intent_type:
            filters.append("pq.intent_type = %s")
            params.append(intent_type)
        if status:
            filters.append("ar.status = %s")
            params.append(status)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*)
                FROM answer_runs ar
                LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
                {where_clause}
                """,
                tuple(params),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                       pq.text AS prompt_text,
                       pq.intent_type AS prompt_intent_type,
                       pq.priority AS prompt_priority,
                       pq.prompt_version AS prompt_version
                FROM answer_runs ar
                LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
                LEFT JOIN collection_costs cc ON cc.answer_run_id = ar.id
                LEFT JOIN (
                    SELECT answer_run_id, count(*) AS citation_count
                    FROM answer_citations
                    GROUP BY answer_run_id
                ) citation_counts ON citation_counts.answer_run_id = ar.id
                LEFT JOIN (
                    SELECT target_id AS answer_run_id, count(*) AS audit_event_count
                    FROM audit_events
                    WHERE target_type = 'answer_run'
                    GROUP BY target_id
                ) audit_counts ON audit_counts.answer_run_id = ar.id::text
                {where_clause}
                ORDER BY {order_by}
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            answer_runs = _rows_dict(cursor.fetchall(), ANSWER_RUN_READ_COLUMNS)
            records: list[RuntimeEvidenceRun] = []
            for answer_run in answer_runs:
                answer_run_id = str(answer_run["id"])
                records.append(self._load_runtime_evidence_run(cursor=cursor, answer_run=answer_run, answer_run_id=answer_run_id))
        return RuntimeEvidencePage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            sort=sort_key,
            records=tuple(records),
        )

    def list_runtime_collection_runs(
        self,
        *,
        project_id: str | None = None,
        run_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeCollectionRunPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if run_type:
            filters.append("run_type = %s")
            params.append(run_type)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM collection_run_summaries {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(COLLECTION_RUN_SUMMARY_COLUMNS)}
                FROM collection_run_summaries
                {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            runs = tuple(
                _runtime_collection_run_row(run)
                for run in _rows_dict(cursor.fetchall(), COLLECTION_RUN_SUMMARY_COLUMNS)
            )
            records: list[RuntimeCollectionRun] = []
            for run in runs:
                cursor.execute(
                    f"""
                    SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                    FROM audit_events
                    WHERE target_type = %s AND target_id = %s
                    ORDER BY created_at ASC
                    """,
                    ("collection_run", str(run["id"])),
                )
                records.append(
                    RuntimeCollectionRun(
                        collection_run=run,
                        audit_events=_rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS),
                    )
                )
        return RuntimeCollectionRunPage(total_count=total_count, limit=limit, offset=offset, records=tuple(records))

    def export_runtime_collection_runs_csv(
        self,
        *,
        project_id: str,
        run_type: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        normalized_project_id = project_id.strip()
        if not normalized_project_id:
            raise ValueError("project_id is required")
        normalized_run_type = run_type.strip() if run_type else None
        page = self.list_runtime_collection_runs(
            project_id=normalized_project_id,
            run_type=normalized_run_type,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_collection_runs_csv(page)
        filters = {
            "project_id": normalized_project_id,
            "run_type": normalized_run_type,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_collection_runs_csv",
            filename="runtime-collection-runs.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=page.total_count,
            row_count=len(page.records),
        )

    def export_runtime_evidence_csv(
        self,
        *,
        project_id: str | None = None,
        platform: str | None = None,
        city: str | None = None,
        intent_type: str | None = None,
        status: str | None = None,
        sort: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        page = self.list_runtime_evidence_runs(
            project_id=project_id,
            platform=platform,
            city=city,
            intent_type=intent_type,
            status=status,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_evidence_csv(page)
        filters = {
            "project_id": project_id,
            "platform": platform,
            "city": city,
            "intent_type": intent_type,
            "status": status,
            "sort": page.sort,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_evidence_csv",
            filename="runtime-evidence.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=page.total_count,
            row_count=len(page.records),
        )

    def list_runtime_saved_views(
        self,
        *,
        project_id: str | None = None,
        view_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> RuntimeSavedViewPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if view_type:
            filters.append("view_type = %s")
            params.append(view_type)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM runtime_saved_views {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_SAVED_VIEW_COLUMNS)}
                FROM runtime_saved_views
                {where_clause}
                ORDER BY updated_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            saved_views = _rows_dict(cursor.fetchall(), RUNTIME_SAVED_VIEW_COLUMNS)
            records = tuple(self._load_runtime_saved_view(cursor=cursor, saved_view=saved_view) for saved_view in saved_views)
        return RuntimeSavedViewPage(total_count=total_count, limit=limit, offset=offset, records=records)

    def save_runtime_saved_view(self, view: RuntimeSavedViewInput) -> RuntimeSavedView:
        view_id = _stable_id("runtime-saved-view", view.project_id, view.name)
        after = {
            "id": view_id,
            "project_id": view.project_id,
            "name": view.name,
            "view_type": view.view_type,
            "filters": view.filters,
            "sort": view.sort,
            "query_path": view.query_path,
            "export_path": view.export_path,
            "created_by": view.created_by,
        }
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_SAVED_VIEW_COLUMNS)}
                FROM runtime_saved_views
                WHERE project_id = %s AND name = %s
                LIMIT 1
                """,
                (_uuid(view.project_id), view.name),
            )
            existing = cursor.fetchone()
            before = _row_dict(existing, RUNTIME_SAVED_VIEW_COLUMNS) if existing else None
            cursor.execute(
                """
                INSERT INTO runtime_saved_views (
                  id, project_id, name, view_type, filters, sort, query_path, export_path,
                  created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id, name) DO UPDATE SET
                  view_type = EXCLUDED.view_type,
                  filters = EXCLUDED.filters,
                  sort = EXCLUDED.sort,
                  query_path = EXCLUDED.query_path,
                  export_path = EXCLUDED.export_path,
                  created_by = EXCLUDED.created_by,
                  updated_at = now()
                """,
                (
                    _uuid(view_id),
                    _uuid(view.project_id),
                    view.name,
                    view.view_type,
                    _json_payload(view.filters),
                    view.sort,
                    view.query_path,
                    view.export_path,
                    view.created_by,
                ),
            )
            audit_event = build_audit_event(
                event_type="runtime_saved_view_saved",
                project_id=view.project_id,
                actor_type="user",
                actor_id=view.created_by,
                target_type="runtime_saved_view",
                target_id=view_id,
                before=before,
                after=after,
                input_refs={"query_path": [view.query_path], "export_path": [view.export_path]},
                output_refs={"runtime_saved_view_ids": [view_id]},
                method_version="runtime_saved_view_v1",
                reason="save runtime evidence filter view",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_SAVED_VIEW_COLUMNS)}
                FROM runtime_saved_views
                WHERE id = %s
                """,
                (_uuid(view_id),),
            )
            saved_view = _row_dict(cursor.fetchone(), RUNTIME_SAVED_VIEW_COLUMNS)
            record = self._load_runtime_saved_view(cursor=cursor, saved_view=saved_view)
        self.connection.commit()
        return record

    def _load_runtime_saved_view(self, *, cursor: DbCursor, saved_view: dict[str, Any]) -> RuntimeSavedView:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            """,
            (_uuid(saved_view["project_id"]), "runtime_saved_view", str(saved_view["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeSavedView(saved_view=saved_view, audit_events=audit_events)

    def get_project_brand_kit(self, *, project_id: str) -> RuntimeProjectBrandKit | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_BRAND_KIT_COLUMNS)}
                FROM project_brand_kits
                WHERE project_id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._load_project_brand_kit(
                cursor=cursor,
                brand_kit=_row_dict(row, PROJECT_BRAND_KIT_COLUMNS),
            )

    def save_project_brand_kit(self, brand_kit: RuntimeProjectBrandKitInput) -> RuntimeProjectBrandKit:
        project_id = brand_kit.project_id.strip()
        client_name = brand_kit.client_name.strip()
        prepared_by = brand_kit.prepared_by.strip() or "GENO SaaS AU"
        updated_by = brand_kit.updated_by.strip() or "runtime-console"
        if not project_id:
            raise ValueError("project_id is required")
        if not client_name:
            raise ValueError("client_name is required")
        kit_id = _stable_id("project-brand-kit", project_id)
        after = {
            "id": kit_id,
            "project_id": project_id,
            "client_name": client_name,
            "prepared_by": prepared_by,
            "logo_url": brand_kit.logo_url.strip() if brand_kit.logo_url else None,
            "primary_color": brand_kit.primary_color.strip() if brand_kit.primary_color else None,
            "secondary_color": brand_kit.secondary_color.strip() if brand_kit.secondary_color else None,
            "footer_text": brand_kit.footer_text.strip() if brand_kit.footer_text else None,
            "updated_by": updated_by,
        }
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            if not cursor.fetchone():
                raise ValueError("project not found")
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_BRAND_KIT_COLUMNS)}
                FROM project_brand_kits
                WHERE project_id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            existing = cursor.fetchone()
            before = _row_dict(existing, PROJECT_BRAND_KIT_COLUMNS) if existing else None
            cursor.execute(
                """
                INSERT INTO project_brand_kits (
                  id, project_id, client_name, prepared_by, logo_url, primary_color,
                  secondary_color, footer_text, updated_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id) DO UPDATE SET
                  client_name = EXCLUDED.client_name,
                  prepared_by = EXCLUDED.prepared_by,
                  logo_url = EXCLUDED.logo_url,
                  primary_color = EXCLUDED.primary_color,
                  secondary_color = EXCLUDED.secondary_color,
                  footer_text = EXCLUDED.footer_text,
                  updated_by = EXCLUDED.updated_by,
                  updated_at = now()
                """,
                (
                    _uuid(kit_id),
                    _uuid(project_id),
                    after["client_name"],
                    after["prepared_by"],
                    after["logo_url"],
                    after["primary_color"],
                    after["secondary_color"],
                    after["footer_text"],
                    after["updated_by"],
                ),
            )
            audit_event = build_audit_event(
                event_type="project_brand_kit_saved",
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="project_brand_kit",
                target_id=kit_id,
                before=before,
                after=after,
                input_refs={"project_ids": [project_id]},
                output_refs={"project_brand_kit_ids": [kit_id]},
                method_version="project_brand_kit_v1",
                reason="save project white-label brand configuration",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_BRAND_KIT_COLUMNS)}
                FROM project_brand_kits
                WHERE project_id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            saved_row = cursor.fetchone()
            record = self._load_project_brand_kit(
                cursor=cursor,
                brand_kit=_row_dict(saved_row, PROJECT_BRAND_KIT_COLUMNS),
            )
        self.connection.commit()
        return record

    def upload_project_brand_logo(self, upload: RuntimeProjectBrandLogoUpload) -> RuntimeProjectBrandKit:
        project_id = upload.project_id.strip()
        logo_url = upload.logo_url.strip()
        filename = upload.filename.strip() or "logo.bin"
        content_type = upload.content_type.strip() or "application/octet-stream"
        uploaded_by = upload.uploaded_by.strip() or "runtime-console"
        content_hash = upload.content_hash.strip()
        if not project_id:
            raise ValueError("project_id is required")
        if not logo_url:
            raise ValueError("logo_url is required")
        if not content_hash:
            raise ValueError("content_hash is required")
        kit_id = _stable_id("project-brand-kit", project_id)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, target_brand
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            project_row = cursor.fetchone()
            if not project_row:
                raise ValueError("project not found")
            project = _row_dict(project_row, ("id", "target_brand"))
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_BRAND_KIT_COLUMNS)}
                FROM project_brand_kits
                WHERE project_id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            existing_row = cursor.fetchone()
            before = _row_dict(existing_row, PROJECT_BRAND_KIT_COLUMNS) if existing_row else None
            existing = before or {}
            after = {
                "id": kit_id,
                "project_id": project_id,
                "client_name": existing.get("client_name") or project.get("target_brand") or "Client",
                "prepared_by": existing.get("prepared_by") or "GENO SaaS AU",
                "logo_url": logo_url,
                "primary_color": existing.get("primary_color"),
                "secondary_color": existing.get("secondary_color"),
                "footer_text": existing.get("footer_text"),
                "updated_by": uploaded_by,
            }
            cursor.execute(
                """
                INSERT INTO project_brand_kits (
                  id, project_id, client_name, prepared_by, logo_url, primary_color,
                  secondary_color, footer_text, updated_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id) DO UPDATE SET
                  logo_url = EXCLUDED.logo_url,
                  updated_by = EXCLUDED.updated_by,
                  updated_at = now()
                """,
                (
                    _uuid(kit_id),
                    _uuid(project_id),
                    after["client_name"],
                    after["prepared_by"],
                    after["logo_url"],
                    after["primary_color"],
                    after["secondary_color"],
                    after["footer_text"],
                    after["updated_by"],
                ),
            )
            audit_event = build_audit_event(
                event_type="project_brand_logo_uploaded",
                project_id=project_id,
                actor_type="user",
                actor_id=uploaded_by,
                target_type="project_brand_kit",
                target_id=kit_id,
                before=before,
                after=after,
                input_refs={
                    "project_ids": [project_id],
                    "source_filename": [filename],
                    "source_content_type": [content_type],
                    "content_hash": [content_hash],
                },
                output_refs={
                    "project_brand_kit_ids": [kit_id],
                    "logo_url": [logo_url],
                },
                method_version="project_brand_logo_upload_v1",
                reason="archive project brand logo asset and update white-label defaults",
            )
            asset_input = RuntimeProjectBrandAssetInput(
                project_id=project_id,
                asset_type="logo",
                asset_url=logo_url,
                category="brand_logo",
                source_filename=filename,
                source_content_type=content_type,
                content_hash=content_hash,
                storage_version=content_hash,
                status="active",
                uploaded_by=uploaded_by,
                metadata={"source": "logo_upload", "brand_kit_id": kit_id},
                reason="register archived project brand logo in asset library",
            )
            asset_before, asset_after = self._upsert_project_brand_asset(cursor=cursor, asset=asset_input)
            asset_audit_event = self._build_project_brand_asset_audit_event(
                before=asset_before,
                after=asset_after,
                asset=asset_input,
            )
            self.save_audit_events((audit_event, asset_audit_event), cursor=cursor)
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_BRAND_KIT_COLUMNS)}
                FROM project_brand_kits
                WHERE project_id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            saved_row = cursor.fetchone()
            record = self._load_project_brand_kit(
                cursor=cursor,
                brand_kit=_row_dict(saved_row, PROJECT_BRAND_KIT_COLUMNS),
            )
        self.connection.commit()
        return record

    def save_project_brand_asset(self, asset: RuntimeProjectBrandAssetInput) -> RuntimeProjectBrandAsset:
        project_id = asset.project_id.strip()
        if not project_id:
            raise ValueError("project_id is required")
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            if not cursor.fetchone():
                raise ValueError("project not found")
            before, after = self._upsert_project_brand_asset(cursor=cursor, asset=asset)
            audit_event = self._build_project_brand_asset_audit_event(
                before=before,
                after=after,
                asset=asset,
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            record = self._load_project_brand_asset(cursor=cursor, asset=after)
        self.connection.commit()
        return record

    def get_project_brand_asset_project_id(self, *, asset_id: str) -> str | None:
        clean_asset_id = asset_id.strip()
        if not clean_asset_id:
            raise ValueError("asset_id is required")
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT project_id
                FROM project_brand_assets
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(clean_asset_id),),
            )
            row = cursor.fetchone()
        if not row:
            return None
        if isinstance(row, dict):
            return str(row["project_id"])
        return str(row[0])

    def update_project_brand_asset_scan_status(
        self,
        scan: RuntimeProjectBrandAssetScanInput,
    ) -> RuntimeProjectBrandAsset:
        asset_id = scan.asset_id.strip()
        scan_status = scan.scan_status.strip().lower()
        scanned_by = scan.scanned_by.strip() or "runtime-console"
        scan_method_version = scan.scan_method_version.strip() or "manual_asset_scan_v1"
        scan_notes = scan.scan_notes.strip() if scan.scan_notes else None
        reason = scan.reason.strip() if scan.reason else None
        if not asset_id:
            raise ValueError("asset_id is required")
        if scan_status not in {"pending", "passed", "failed", "skipped"}:
            raise ValueError("scan_status must be pending, passed, failed, or skipped")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_BRAND_ASSET_COLUMNS)}
                FROM project_brand_assets
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(asset_id),),
            )
            existing_row = cursor.fetchone()
            if not existing_row:
                raise ValueError("project brand asset not found")
            before = _row_dict(existing_row, PROJECT_BRAND_ASSET_COLUMNS)
            cursor.execute(
                f"""
                UPDATE project_brand_assets
                SET scan_status = %s,
                    scan_checked_at = now(),
                    scan_method_version = %s,
                    scan_notes = %s,
                    updated_at = now()
                WHERE id = %s
                RETURNING {", ".join(PROJECT_BRAND_ASSET_COLUMNS)}
                """,
                (scan_status, scan_method_version, scan_notes, _uuid(asset_id)),
            )
            after = _row_dict(cursor.fetchone(), PROJECT_BRAND_ASSET_COLUMNS)
            audit_event = build_audit_event(
                event_type="project_brand_asset_scan_recorded",
                project_id=str(after["project_id"]),
                actor_type="user",
                actor_id=scanned_by,
                target_type="project_brand_asset",
                target_id=str(after["id"]),
                before=before,
                after=after,
                input_refs={
                    "project_brand_asset_ids": [str(after["id"])],
                    "asset_url": [str(after["asset_url"])],
                    "scan_status": [scan_status],
                },
                output_refs={
                    "project_brand_asset_ids": [str(after["id"])],
                    "scan_status": [scan_status],
                    "scan_method_version": [scan_method_version],
                },
                method_version=scan_method_version,
                reason=reason or "record project brand asset scan status",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            record = self._load_project_brand_asset(cursor=cursor, asset=after)
        self.connection.commit()
        return record

    def list_project_brand_assets(
        self,
        *,
        project_id: str,
        asset_type: str | None = None,
        category: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeProjectBrandAssetPage:
        project_id = project_id.strip()
        if not project_id:
            raise ValueError("project_id is required")
        filters = ["project_id = %s"]
        params: list[object] = [_uuid(project_id)]
        if asset_type and asset_type.strip():
            filters.append("asset_type = %s")
            params.append(asset_type.strip().lower())
        if category and category.strip():
            filters.append("category = %s")
            params.append(category.strip().lower())
        if status and status.strip():
            filters.append("status = %s")
            params.append(status.strip().lower())
        where_clause = " AND ".join(filters)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*)
                FROM project_brand_assets
                WHERE {where_clause}
                """,
                tuple(params),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row["count"] if isinstance(total_row, dict) else total_row[0])
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_BRAND_ASSET_COLUMNS)}
                FROM project_brand_assets
                WHERE {where_clause}
                ORDER BY updated_at DESC, created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                tuple([*params, limit, offset]),
            )
            rows = _rows_dict(cursor.fetchall(), PROJECT_BRAND_ASSET_COLUMNS)
            records = tuple(self._load_project_brand_asset(cursor=cursor, asset=row) for row in rows)
        return RuntimeProjectBrandAssetPage(
            project_id=project_id,
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def list_project_brand_asset_versions(
        self,
        *,
        project_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> RuntimeProjectBrandAssetVersionPage:
        if not project_id.strip():
            raise ValueError("project_id is required")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_BRAND_KIT_COLUMNS)}
                FROM project_brand_kits
                WHERE project_id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            brand_kit_row = cursor.fetchone()
            active_logo_url = None
            if brand_kit_row:
                active_logo_url = _row_dict(brand_kit_row, PROJECT_BRAND_KIT_COLUMNS).get("logo_url")
            cursor.execute(
                """
                SELECT count(*)
                FROM audit_events
                WHERE project_id = %s AND target_type = %s
                  AND event_type IN (%s, %s)
                  AND output_refs ? %s
                """,
                (
                    _uuid(project_id),
                    "project_brand_kit",
                    "project_brand_logo_uploaded",
                    "project_brand_logo_version_activated",
                    "logo_url",
                ),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row["count"] if isinstance(total_row, dict) else total_row[0])
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE project_id = %s AND target_type = %s
                  AND event_type IN (%s, %s)
                  AND output_refs ? %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (
                    _uuid(project_id),
                    "project_brand_kit",
                    "project_brand_logo_uploaded",
                    "project_brand_logo_version_activated",
                    "logo_url",
                    limit,
                    offset,
                ),
            )
            audit_rows = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeProjectBrandAssetVersionPage(
            project_id=project_id,
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=tuple(
                self._project_brand_asset_version_from_audit_event(
                    audit_event=row,
                    active_logo_url=active_logo_url,
                )
                for row in audit_rows
            ),
        )

    def activate_project_brand_logo_version(
        self,
        activation: RuntimeProjectBrandAssetActivationInput,
    ) -> RuntimeProjectBrandKit:
        project_id = activation.project_id.strip()
        asset_url = activation.asset_url.strip()
        activated_by = activation.activated_by.strip() or "runtime-console"
        reason = activation.reason.strip() if activation.reason else None
        if not project_id:
            raise ValueError("project_id is required")
        if not asset_url:
            raise ValueError("asset_url is required")
        kit_id = _stable_id("project-brand-kit", project_id)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, target_brand
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            project_row = cursor.fetchone()
            if not project_row:
                raise ValueError("project not found")
            project = _row_dict(project_row, ("id", "target_brand"))
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE project_id = %s AND target_type = %s
                  AND event_type IN (%s, %s)
                  AND output_refs ? %s
                ORDER BY created_at DESC
                """,
                (
                    _uuid(project_id),
                    "project_brand_kit",
                    "project_brand_logo_uploaded",
                    "project_brand_logo_version_activated",
                    "logo_url",
                ),
            )
            version_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
            matching_event = next(
                (
                    row
                    for row in version_events
                    if asset_url in [str(value) for value in row.get("output_refs", {}).get("logo_url", [])]
                ),
                None,
            )
            if matching_event is None:
                raise ValueError("brand asset version not found")
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_BRAND_KIT_COLUMNS)}
                FROM project_brand_kits
                WHERE project_id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            existing_row = cursor.fetchone()
            before = _row_dict(existing_row, PROJECT_BRAND_KIT_COLUMNS) if existing_row else None
            existing = before or {}
            after = {
                "id": kit_id,
                "project_id": project_id,
                "client_name": existing.get("client_name") or project.get("target_brand") or "Client",
                "prepared_by": existing.get("prepared_by") or "GENO SaaS AU",
                "logo_url": asset_url,
                "primary_color": existing.get("primary_color"),
                "secondary_color": existing.get("secondary_color"),
                "footer_text": existing.get("footer_text"),
                "updated_by": activated_by,
            }
            cursor.execute(
                """
                INSERT INTO project_brand_kits (
                  id, project_id, client_name, prepared_by, logo_url, primary_color,
                  secondary_color, footer_text, updated_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id) DO UPDATE SET
                  logo_url = EXCLUDED.logo_url,
                  updated_by = EXCLUDED.updated_by,
                  updated_at = now()
                """,
                (
                    _uuid(kit_id),
                    _uuid(project_id),
                    after["client_name"],
                    after["prepared_by"],
                    after["logo_url"],
                    after["primary_color"],
                    after["secondary_color"],
                    after["footer_text"],
                    after["updated_by"],
                ),
            )
            audit_event = build_audit_event(
                event_type="project_brand_logo_version_activated",
                project_id=project_id,
                actor_type="user",
                actor_id=activated_by,
                target_type="project_brand_kit",
                target_id=kit_id,
                before=before,
                after=after,
                input_refs={
                    "project_ids": [project_id],
                    "source_audit_event_ids": [str(matching_event["id"])],
                },
                output_refs={
                    "project_brand_kit_ids": [kit_id],
                    "logo_url": [asset_url],
                },
                method_version="project_brand_logo_asset_version_v1",
                reason=reason or "activate project brand logo asset version",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_BRAND_KIT_COLUMNS)}
                FROM project_brand_kits
                WHERE project_id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            saved_row = cursor.fetchone()
            record = self._load_project_brand_kit(
                cursor=cursor,
                brand_kit=_row_dict(saved_row, PROJECT_BRAND_KIT_COLUMNS),
            )
        self.connection.commit()
        return record

    def _load_project_brand_kit(self, *, cursor: DbCursor, brand_kit: dict[str, Any]) -> RuntimeProjectBrandKit:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (_uuid(brand_kit["project_id"]), "project_brand_kit", str(brand_kit["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeProjectBrandKit(brand_kit=brand_kit, audit_events=audit_events)

    def _upsert_project_brand_asset(
        self,
        *,
        cursor: DbCursor,
        asset: RuntimeProjectBrandAssetInput,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        project_id = asset.project_id.strip()
        asset_url = asset.asset_url.strip()
        asset_type = asset.asset_type.strip().lower()
        category = asset.category.strip().lower() if asset.category else "uncategorized"
        status = asset.status.strip().lower() if asset.status else "active"
        uploaded_by = asset.uploaded_by.strip() or "runtime-console"
        preview_url = asset.preview_url.strip() if asset.preview_url else None
        source_filename = asset.source_filename.strip() if asset.source_filename else None
        source_content_type = asset.source_content_type.strip() if asset.source_content_type else None
        content_hash = asset.content_hash.strip() if asset.content_hash else None
        storage_version = asset.storage_version.strip() if asset.storage_version else content_hash
        if not project_id:
            raise ValueError("project_id is required")
        if not asset_type:
            raise ValueError("asset_type is required")
        if not asset_url:
            raise ValueError("asset_url is required")
        if status not in {"active", "draft", "archived"}:
            raise ValueError("asset status must be active, draft, or archived")
        asset_id = _stable_id("project-brand-asset", project_id, asset_url)
        cursor.execute(
            f"""
            SELECT {", ".join(PROJECT_BRAND_ASSET_COLUMNS)}
            FROM project_brand_assets
            WHERE project_id = %s AND asset_url = %s
            LIMIT 1
            """,
            (_uuid(project_id), asset_url),
        )
        existing_row = cursor.fetchone()
        before = _row_dict(existing_row, PROJECT_BRAND_ASSET_COLUMNS) if existing_row else None
        cursor.execute(
            """
            INSERT INTO project_brand_assets (
              id, project_id, asset_type, asset_url, category, preview_url, source_filename,
              source_content_type, content_hash, storage_version, status, uploaded_by, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id, asset_url) DO UPDATE SET
              asset_type = EXCLUDED.asset_type,
              category = EXCLUDED.category,
              preview_url = EXCLUDED.preview_url,
              source_filename = EXCLUDED.source_filename,
              source_content_type = EXCLUDED.source_content_type,
              content_hash = EXCLUDED.content_hash,
              storage_version = EXCLUDED.storage_version,
              status = EXCLUDED.status,
              uploaded_by = EXCLUDED.uploaded_by,
              metadata = EXCLUDED.metadata,
              updated_at = now()
            """,
            (
                _uuid(asset_id),
                _uuid(project_id),
                asset_type,
                asset_url,
                category,
                preview_url,
                source_filename,
                source_content_type,
                content_hash,
                storage_version,
                status,
                uploaded_by,
                _json_payload(asset.metadata),
            ),
        )
        cursor.execute(
            f"""
            SELECT {", ".join(PROJECT_BRAND_ASSET_COLUMNS)}
            FROM project_brand_assets
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(asset_id),),
        )
        after = _row_dict(cursor.fetchone(), PROJECT_BRAND_ASSET_COLUMNS)
        return before, after

    @staticmethod
    def _build_project_brand_asset_audit_event(
        *,
        before: dict[str, Any] | None,
        after: dict[str, Any],
        asset: RuntimeProjectBrandAssetInput,
    ) -> AuditEvent:
        content_hash = after.get("content_hash")
        storage_version = after.get("storage_version")
        input_refs: dict[str, list[str]] = {
            "project_ids": [str(after["project_id"])],
            "asset_url": [str(after["asset_url"])],
        }
        if after.get("source_filename"):
            input_refs["source_filename"] = [str(after["source_filename"])]
        if after.get("source_content_type"):
            input_refs["source_content_type"] = [str(after["source_content_type"])]
        if after.get("preview_url"):
            input_refs["preview_url"] = [str(after["preview_url"])]
        if content_hash:
            input_refs["content_hash"] = [str(content_hash)]
        output_refs: dict[str, list[str]] = {
            "project_brand_asset_ids": [str(after["id"])],
            "asset_url": [str(after["asset_url"])],
        }
        if storage_version:
            output_refs["storage_version"] = [str(storage_version)]
        uploaded_by = asset.uploaded_by.strip() or str(after.get("uploaded_by") or "runtime-console")
        reason = asset.reason.strip() if asset.reason else None
        return build_audit_event(
            event_type="project_brand_asset_registered",
            project_id=str(after["project_id"]),
            actor_type="user",
            actor_id=uploaded_by,
            target_type="project_brand_asset",
            target_id=str(after["id"]),
            before=before,
            after=after,
            input_refs=input_refs,
            output_refs=output_refs,
            method_version="project_brand_asset_library_v1",
            reason=reason or "register project brand asset in library",
        )

    def _load_project_brand_asset(self, *, cursor: DbCursor, asset: dict[str, Any]) -> RuntimeProjectBrandAsset:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (_uuid(asset["project_id"]), "project_brand_asset", str(asset["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeProjectBrandAsset(asset=asset, audit_events=audit_events)

    @staticmethod
    def _project_brand_asset_version_from_audit_event(
        *,
        audit_event: dict[str, Any],
        active_logo_url: str | None,
    ) -> RuntimeProjectBrandAssetVersion:
        output_refs = audit_event.get("output_refs", {}) or {}
        input_refs = audit_event.get("input_refs", {}) or {}
        logo_urls = output_refs.get("logo_url", []) or []
        asset_url = str(logo_urls[0]) if logo_urls else ""
        filenames = input_refs.get("source_filename", []) or []
        content_types = input_refs.get("source_content_type", []) or []
        content_hashes = input_refs.get("content_hash", []) or []
        return RuntimeProjectBrandAssetVersion(
            version_id=str(audit_event["id"]),
            project_id=str(audit_event["project_id"]),
            asset_type="logo",
            asset_url=asset_url,
            source_filename=str(filenames[0]) if filenames else None,
            source_content_type=str(content_types[0]) if content_types else None,
            content_hash=str(content_hashes[0]) if content_hashes else None,
            uploaded_by=str(audit_event.get("actor_id") or "") or None,
            uploaded_at=audit_event.get("created_at"),
            is_active=bool(asset_url and active_logo_url == asset_url),
            audit_event=audit_event,
        )

    def get_score_weight_config(
        self,
        *,
        project_id: str,
        formula_version: str = "au_visibility_v1",
    ) -> RuntimeScoreWeightConfig | None:
        formula = get_score_formula(formula_version)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(SCORE_WEIGHT_CONFIG_COLUMNS)}
                FROM score_weight_configs
                WHERE project_id = %s AND formula_version = %s
                LIMIT 1
                """,
                (_uuid(project_id), formula.formula_version),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._load_score_weight_config(
                cursor=cursor,
                config=_row_dict(row, SCORE_WEIGHT_CONFIG_COLUMNS),
            )

    def list_score_weight_profiles(self, *, include_archived: bool = False) -> RuntimeScoreWeightProfilePage:
        system_profiles = tuple(
            RuntimeScoreWeightProfile(score_weight_profile=profile, audit_events=())
            for profile in list_score_weight_profiles()
            if include_archived or str(profile.get("status")) != "archived"
        )
        with self.connection.cursor() as cursor:
            where_clause = "" if include_archived else "WHERE status <> 'archived'"
            cursor.execute(
                f"""
                SELECT {", ".join(SCORE_WEIGHT_PROFILE_COLUMNS)}
                FROM score_weight_profiles
                {where_clause}
                ORDER BY is_system DESC, updated_at DESC, profile_key ASC
                """,
            )
            custom_profiles = tuple(
                RuntimeScoreWeightProfile(score_weight_profile=row, audit_events=())
                for row in _rows_dict(cursor.fetchall(), SCORE_WEIGHT_PROFILE_COLUMNS)
            )
        records = (*system_profiles, *custom_profiles)
        return RuntimeScoreWeightProfilePage(total_count=len(records), records=records)

    def get_score_weight_profile(self, profile_key: str) -> RuntimeScoreWeightProfile | None:
        profile_key = profile_key.strip() or "au_visibility_v1"
        for profile in list_score_weight_profiles():
            if str(profile.get("profile_key")) == profile_key:
                return RuntimeScoreWeightProfile(score_weight_profile=profile, audit_events=())
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(SCORE_WEIGHT_PROFILE_COLUMNS)}
                FROM score_weight_profiles
                WHERE profile_key = %s
                LIMIT 1
                """,
                (profile_key,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return RuntimeScoreWeightProfile(
                score_weight_profile=_row_dict(row, SCORE_WEIGHT_PROFILE_COLUMNS),
                audit_events=(),
            )

    def save_score_weight_profile(self, profile: RuntimeScoreWeightProfileInput) -> RuntimeScoreWeightProfile:
        profile_key = profile.profile_key.strip()
        name = profile.name.strip()
        base_formula_version = profile.base_formula_version.strip() or "au_visibility_v1"
        updated_by = profile.updated_by.strip() or "runtime-console"
        created_by = profile.created_by.strip() or updated_by
        status = profile.status.strip().lower() or "active"
        if not profile_key:
            raise ValueError("profile_key is required")
        if not name:
            raise ValueError("name is required")
        if profile_key in {str(item["profile_key"]) for item in list_score_weight_profiles()}:
            raise ValueError("system score profile cannot be overwritten; save as a new custom profile")
        if status not in {"active", "archived"}:
            raise ValueError("status must be active or archived")
        base_formula = get_score_formula(base_formula_version)
        weights = normalize_score_weights(profile.weights, formula_version=base_formula.formula_version)
        profile_id = _stable_id("score-weight-profile", profile_key)
        after = {
            "id": profile_id,
            "profile_key": profile_key,
            "name": name,
            "description": profile.description.strip() if profile.description else None,
            "base_formula_version": base_formula.formula_version,
            "weights": weights,
            "scope": "global",
            "is_system": False,
            "status": status,
            "created_by": created_by,
            "updated_by": updated_by,
        }
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(SCORE_WEIGHT_PROFILE_COLUMNS)}
                FROM score_weight_profiles
                WHERE profile_key = %s
                LIMIT 1
                """,
                (profile_key,),
            )
            existing = cursor.fetchone()
            before = _row_dict(existing, SCORE_WEIGHT_PROFILE_COLUMNS) if existing else None
            cursor.execute(
                """
                INSERT INTO score_weight_profiles (
                  id, profile_key, name, description, base_formula_version, weights, scope,
                  is_system, status, created_by, updated_by
                ) VALUES (%s, %s, %s, %s, %s, %s, 'global', false, %s, %s, %s)
                ON CONFLICT (profile_key) DO UPDATE SET
                  name = EXCLUDED.name,
                  description = EXCLUDED.description,
                  base_formula_version = EXCLUDED.base_formula_version,
                  weights = EXCLUDED.weights,
                  status = EXCLUDED.status,
                  updated_by = EXCLUDED.updated_by,
                  updated_at = now()
                """,
                (
                    _uuid(profile_id),
                    profile_key,
                    name,
                    after["description"],
                    base_formula.formula_version,
                    _json_payload(weights),
                    status,
                    created_by,
                    updated_by,
                ),
            )
            cursor.execute(
                f"""
                SELECT {", ".join(SCORE_WEIGHT_PROFILE_COLUMNS)}
                FROM score_weight_profiles
                WHERE profile_key = %s
                LIMIT 1
                """,
                (profile_key,),
            )
            saved = _row_dict(cursor.fetchone(), SCORE_WEIGHT_PROFILE_COLUMNS)
        self.connection.commit()
        return RuntimeScoreWeightProfile(score_weight_profile=saved, audit_events=())

    def save_score_weight_config(self, config: RuntimeScoreWeightConfigInput) -> RuntimeScoreWeightConfig:
        project_id = config.project_id.strip()
        formula_version = config.formula_version.strip() or "au_visibility_v1"
        updated_by = config.updated_by.strip() or "runtime-console"
        formula = get_score_formula(formula_version)
        if not project_id:
            raise ValueError("project_id is required")
        weights = normalize_score_weights(config.weights, formula_version=formula.formula_version)
        config_id = _stable_id("score-weight-config", project_id, formula.formula_version)
        after = {
            "id": config_id,
            "project_id": project_id,
            "formula_version": formula.formula_version,
            "weights": weights,
            "updated_by": updated_by,
            "notes": config.notes.strip() if config.notes else None,
        }
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            if not cursor.fetchone():
                raise ValueError("project not found")
            cursor.execute(
                f"""
                SELECT {", ".join(SCORE_WEIGHT_CONFIG_COLUMNS)}
                FROM score_weight_configs
                WHERE project_id = %s AND formula_version = %s
                LIMIT 1
                """,
                (_uuid(project_id), formula.formula_version),
            )
            existing = cursor.fetchone()
            before = _row_dict(existing, SCORE_WEIGHT_CONFIG_COLUMNS) if existing else None
            cursor.execute(
                """
                INSERT INTO score_weight_configs (
                  id, project_id, formula_version, weights, updated_by, notes
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id, formula_version) DO UPDATE SET
                  weights = EXCLUDED.weights,
                  updated_by = EXCLUDED.updated_by,
                  notes = EXCLUDED.notes,
                  updated_at = now()
                """,
                (
                    _uuid(config_id),
                    _uuid(project_id),
                    formula.formula_version,
                    _json_payload(weights),
                    updated_by,
                    after["notes"],
                ),
            )
            audit_event = build_audit_event(
                event_type="score_weight_config_saved",
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="score_weight_config",
                target_id=config_id,
                before=before,
                after=after,
                input_refs={"project_ids": [project_id]},
                output_refs={"score_weight_config_ids": [config_id]},
                method_version="score_weight_config_v1",
                reason="save project-level AU visibility score weights",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            cursor.execute(
                f"""
                SELECT {", ".join(SCORE_WEIGHT_CONFIG_COLUMNS)}
                FROM score_weight_configs
                WHERE project_id = %s AND formula_version = %s
                LIMIT 1
                """,
                (_uuid(project_id), formula.formula_version),
            )
            saved_row = cursor.fetchone()
            record = self._load_score_weight_config(
                cursor=cursor,
                config=_row_dict(saved_row, SCORE_WEIGHT_CONFIG_COLUMNS),
            )
        self.connection.commit()
        return record

    def get_score_weights_snapshot(
        self,
        *,
        project_id: str,
        formula_version: str = "au_visibility_v1",
    ) -> dict[str, float]:
        profile = self.get_score_weight_profile(formula_version)
        if profile is not None:
            return normalize_score_weights(
                dict(profile.score_weight_profile.get("weights") or {}),
                formula_version=str(profile.score_weight_profile.get("base_formula_version") or "au_visibility_v1"),
            )
        record = self.get_score_weight_config(project_id=project_id, formula_version=formula_version)
        if record is None:
            return dict(get_score_formula(formula_version).weights)
        return normalize_score_weights(
            dict(record.score_weight_config.get("weights") or {}),
            formula_version=formula_version,
        )

    def _load_score_weight_config(
        self,
        *,
        cursor: DbCursor,
        config: dict[str, Any],
    ) -> RuntimeScoreWeightConfig:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (_uuid(config["project_id"]), "score_weight_config", str(config["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeScoreWeightConfig(score_weight_config=config, audit_events=audit_events)

    def list_runtime_human_reviews(
        self,
        *,
        project_id: str | None = None,
        target_type: str | None = None,
        review_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeHumanReviewPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if target_type:
            filters.append("target_type = %s")
            params.append(target_type)
        if review_status:
            filters.append("review_status = %s")
            params.append(review_status)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM human_review_records {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(HUMAN_REVIEW_COLUMNS)}
                FROM human_review_records
                {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            reviews = _rows_dict(cursor.fetchall(), HUMAN_REVIEW_COLUMNS)
            records = tuple(self._load_runtime_human_review(cursor=cursor, human_review=review) for review in reviews)
        return RuntimeHumanReviewPage(total_count=total_count, limit=limit, offset=offset, records=records)

    def export_runtime_human_reviews_csv(
        self,
        *,
        project_id: str,
        target_type: str | None = None,
        review_status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        normalized_project_id = project_id.strip()
        if not normalized_project_id:
            raise ValueError("project_id is required")
        normalized_target_type = target_type.strip() if target_type else None
        normalized_review_status = review_status.strip().lower() if review_status else None
        page = self.list_runtime_human_reviews(
            project_id=normalized_project_id,
            target_type=normalized_target_type,
            review_status=normalized_review_status,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_human_reviews_csv(page)
        filters = {
            "project_id": normalized_project_id,
            "target_type": normalized_target_type,
            "review_status": normalized_review_status,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_human_reviews_csv",
            filename="runtime-human-reviews.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=page.total_count,
            row_count=len(page.records),
        )

    def list_runtime_human_review_queue(
        self,
        *,
        project_id: str | None = None,
        target_type: str | None = None,
        queue_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeHumanReviewQueuePage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("candidate.project_id = %s")
            params.append(_uuid(project_id))
        if target_type:
            filters.append("candidate.target_type = %s")
            params.append(target_type)
        if queue_status:
            filters.append("candidate.queue_status = %s")
            params.append(queue_status)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        queue_sql = f"""
            WITH review_candidate AS (
              SELECT
                vss.project_id,
                'visibility_score_snapshot' AS target_type,
                vss.id::text AS target_id,
                'Visibility score ' || vss.final_score::text || ' · ' || vss.scope_type || ':' || vss.scope_value AS title,
                vss.created_at,
                CASE WHEN vss.final_score < 60 THEN 10 WHEN vss.final_score < 75 THEN 7 ELSE 5 END AS priority,
                CASE WHEN vss.final_score < 60 THEN 'low_visibility_score' ELSE 'score_snapshot_ready_for_review' END AS reason,
                NULL::text AS source_status,
                jsonb_build_object(
                  'score_snapshot_ids', jsonb_build_array(vss.id::text),
                  'answer_run_ids', to_jsonb(COALESCE(vss.answer_run_ids::text[], ARRAY[]::text[])),
                  'formula_version', vss.formula_version,
                  'final_score', vss.final_score,
                  'trigger_rate', vss.trigger_rate,
                  'mention_rate', vss.mention_rate,
                  'recommendation_rate', vss.recommendation_rate
                ) AS evidence_refs
              FROM visibility_score_snapshots vss
              UNION ALL
              SELECT
                cd.project_id,
                'content_draft' AS target_type,
                cd.id::text AS target_id,
                cd.title AS title,
                cd.created_at,
                CASE
                  WHEN cd.review_status = 'pending_human_review' THEN 9
                  WHEN cd.review_status = 'needs_changes' THEN 6
                  WHEN cd.review_status = 'rejected' THEN 4
                  WHEN cd.review_status IN ('approved', 'acknowledged') THEN 1
                  ELSE 3
                END AS priority,
                'content_draft_' || cd.review_status AS reason,
                cd.review_status AS source_status,
                jsonb_build_object(
                  'content_draft_ids', jsonb_build_array(cd.id::text),
                  'answer_run_ids', to_jsonb(COALESCE(cd.evidence_answer_run_ids::text[], ARRAY[]::text[])),
                  'knowledge_fact_ids', to_jsonb(COALESCE(cd.used_knowledge_fact_ids::text[], ARRAY[]::text[])),
                  'source_gap_types', to_jsonb(COALESCE(cd.source_gap_types, ARRAY[]::text[])),
                  'review_status', cd.review_status,
                  'target_city', cd.target_city,
                  'target_platform', cd.target_platform
                ) AS evidence_refs
              FROM content_drafts cd
            ),
            latest_review AS (
              SELECT DISTINCT ON (target_type, target_id)
                target_type,
                target_id,
                id,
                review_status,
                decision,
                reviewer_id,
                notes,
                payload,
                created_at
              FROM human_review_records
              ORDER BY target_type, target_id, created_at DESC, id DESC
            ),
            candidate AS (
              SELECT
                review_candidate.project_id,
                review_candidate.target_type,
                review_candidate.target_id,
                review_candidate.title,
                review_candidate.created_at,
                review_candidate.priority,
                review_candidate.reason,
                review_candidate.source_status,
                review_candidate.evidence_refs,
                CASE
                  WHEN latest_review.review_status IN ('needs_changes', 'rejected') THEN latest_review.review_status
                  WHEN latest_review.review_status IN ('approved', 'acknowledged') THEN 'reviewed'
                  WHEN review_candidate.source_status IN ('needs_changes', 'rejected') THEN review_candidate.source_status
                  WHEN review_candidate.source_status IN ('approved', 'acknowledged') THEN 'reviewed'
                  ELSE 'pending_review'
                END AS queue_status,
                CASE WHEN latest_review.id IS NULL THEN NULL ELSE jsonb_build_object(
                  'id', latest_review.id::text,
                  'review_status', latest_review.review_status,
                  'decision', latest_review.decision,
                  'reviewer_id', latest_review.reviewer_id,
                  'notes', latest_review.notes,
                  'payload', latest_review.payload,
                  'created_at', latest_review.created_at
                ) END AS latest_review
              FROM review_candidate
              LEFT JOIN latest_review
                ON latest_review.target_type = review_candidate.target_type
               AND latest_review.target_id = review_candidate.target_id
            )
            SELECT *
            FROM candidate
            {where_clause}
        """
        queue_columns = (
            "project_id",
            "target_type",
            "target_id",
            "title",
            "created_at",
            "priority",
            "reason",
            "evidence_refs",
            "queue_status",
            "latest_review",
        )
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM ({queue_sql}) review_queue", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(queue_columns)}
                FROM ({queue_sql}) review_queue
                ORDER BY priority DESC, created_at DESC, target_id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = _rows_dict(cursor.fetchall(), queue_columns)
        records = tuple(
            RuntimeHumanReviewQueueItem(
                project_id=str(row["project_id"]),
                target_type=str(row["target_type"]),
                target_id=str(row["target_id"]),
                title=str(row.get("title") or ""),
                queue_status=str(row.get("queue_status") or "pending_review"),
                priority=int(row.get("priority") or 0),
                reason=str(row.get("reason") or ""),
                created_at=str(row["created_at"]) if row.get("created_at") else None,
                latest_review=dict(row["latest_review"]) if isinstance(row.get("latest_review"), dict) else None,
                evidence_refs=dict(row.get("evidence_refs") or {}),
            )
            for row in rows
        )
        return RuntimeHumanReviewQueuePage(total_count=total_count, limit=limit, offset=offset, records=records)

    def save_human_review(self, review: RuntimeHumanReviewInput) -> RuntimeHumanReviewRecord:
        project_id = review.project_id.strip()
        target_type = review.target_type.strip()
        target_id = review.target_id.strip()
        review_status = review.review_status.strip()
        decision = review.decision.strip()
        reviewer_id = review.reviewer_id.strip() or "runtime-console"
        if not project_id:
            raise ValueError("project_id is required")
        if not target_type:
            raise ValueError("target_type is required")
        if not target_id:
            raise ValueError("target_id is required")
        if not review_status:
            raise ValueError("review_status is required")
        if not decision:
            raise ValueError("decision is required")
        review_id = str(uuid4())
        after = {
            "id": review_id,
            "project_id": project_id,
            "target_type": target_type,
            "target_id": target_id,
            "review_status": review_status,
            "decision": decision,
            "reviewer_id": reviewer_id,
            "notes": review.notes.strip() if review.notes else None,
            "payload": review.payload or {},
        }
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            if not cursor.fetchone():
                raise ValueError("project not found")
            content_draft_before: dict[str, Any] | None = None
            content_draft_after: dict[str, Any] | None = None
            if target_type == "content_draft":
                cursor.execute(
                    f"""
                    SELECT {", ".join(CONTENT_DRAFT_COLUMNS)}
                    FROM content_drafts
                    WHERE id = %s AND project_id = %s
                    LIMIT 1
                    """,
                    (_uuid(target_id), _uuid(project_id)),
                )
                draft_row = cursor.fetchone()
                if not draft_row:
                    raise ValueError("content draft not found")
                content_draft_before = _row_dict(draft_row, CONTENT_DRAFT_COLUMNS)
            cursor.execute(
                """
                INSERT INTO human_review_records (
                  id, project_id, target_type, target_id, review_status,
                  decision, reviewer_id, notes, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    _uuid(review_id),
                    _uuid(project_id),
                    target_type,
                    target_id,
                    review_status,
                    decision,
                    reviewer_id,
                    after["notes"],
                    _json_payload(after["payload"]),
                ),
            )
            if content_draft_before is not None:
                cursor.execute(
                    """
                    UPDATE content_drafts
                    SET review_status = %s
                    WHERE id = %s AND project_id = %s
                    """,
                    (review_status, _uuid(target_id), _uuid(project_id)),
                )
                content_draft_after = {**content_draft_before, "review_status": review_status}
            audit_event = build_audit_event(
                event_type="human_review_recorded",
                project_id=project_id,
                actor_type="user",
                actor_id=reviewer_id,
                target_type="human_review_record",
                target_id=review_id,
                before=None,
                after=after,
                input_refs={"review_target": [{"target_type": target_type, "target_id": target_id}]},
                output_refs={"human_review_record_ids": [review_id]},
                method_version="human_review_v1",
                reason="record human review decision for an auditable runtime object",
            )
            audit_events = [audit_event]
            if content_draft_before is not None and content_draft_after is not None:
                audit_events.append(
                    build_audit_event(
                        event_type="content_draft_review_status_updated",
                        project_id=project_id,
                        actor_type="user",
                        actor_id=reviewer_id,
                        target_type="content_draft",
                        target_id=target_id,
                        before=content_draft_before,
                        after=content_draft_after,
                        input_refs={
                            "human_review_record_ids": [review_id],
                            "review_target": [{"target_type": target_type, "target_id": target_id}],
                        },
                        output_refs={"content_draft_ids": [target_id], "review_status": review_status},
                        method_version="content_draft_review_status_projection_v1",
                        reason="project latest human review decision onto content draft review_status",
                    )
                )
            self.save_audit_events(tuple(audit_events), cursor=cursor)
            cursor.execute(
                f"""
                SELECT {", ".join(HUMAN_REVIEW_COLUMNS)}
                FROM human_review_records
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(review_id),),
            )
            record = self._load_runtime_human_review(
                cursor=cursor,
                human_review=_row_dict(cursor.fetchone(), HUMAN_REVIEW_COLUMNS),
            )
        self.connection.commit()
        return record

    def _load_runtime_human_review(
        self,
        *,
        cursor: DbCursor,
        human_review: dict[str, Any],
    ) -> RuntimeHumanReviewRecord:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (_uuid(human_review["project_id"]), "human_review_record", str(human_review["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeHumanReviewRecord(human_review=human_review, audit_events=audit_events)

    def list_runtime_fidelity_checks(
        self,
        *,
        project_id: str | None = None,
        report_export_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeFidelityCheckPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if report_export_id:
            filters.append("report_export_id = %s")
            params.append(_uuid(report_export_id))
        if status:
            filters.append("status = %s")
            params.append(status)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM api_browser_fidelity_checks {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(API_BROWSER_FIDELITY_CHECK_COLUMNS)}
                FROM api_browser_fidelity_checks
                {where_clause}
                ORDER BY checked_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            checks = _rows_dict(cursor.fetchall(), API_BROWSER_FIDELITY_CHECK_COLUMNS)
            records = tuple(self._load_runtime_fidelity_check(cursor=cursor, fidelity_check=check) for check in checks)
        return RuntimeFidelityCheckPage(total_count=total_count, limit=limit, offset=offset, records=records)

    def export_runtime_fidelity_checks_csv(
        self,
        *,
        project_id: str | None = None,
        report_export_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        normalized_project_id = project_id.strip() if project_id else None
        normalized_report_export_id = report_export_id.strip() if report_export_id else None
        normalized_status = status.strip() if status else None
        page = self.list_runtime_fidelity_checks(
            project_id=normalized_project_id,
            report_export_id=normalized_report_export_id,
            status=normalized_status,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_fidelity_checks_csv(page)
        filters = {
            "project_id": normalized_project_id,
            "report_export_id": normalized_report_export_id,
            "status": normalized_status,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_fidelity_checks_csv",
            filename="runtime-fidelity-checks.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=page.total_count,
            row_count=len(page.records),
        )

    def get_runtime_fidelity_trend(
        self,
        *,
        project_id: str | None = None,
        report_export_id: str | None = None,
        limit: int = 20,
    ) -> RuntimeFidelityTrend:
        limit = max(1, min(limit, 100))
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if report_export_id:
            filters.append("report_export_id = %s")
            params.append(_uuid(report_export_id))
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM api_browser_fidelity_checks {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(API_BROWSER_FIDELITY_CHECK_COLUMNS)}
                FROM api_browser_fidelity_checks
                {where_clause}
                ORDER BY checked_at DESC, id DESC
                LIMIT %s
                """,
                (*params, limit),
            )
            rows_desc = _rows_dict(cursor.fetchall(), API_BROWSER_FIDELITY_CHECK_COLUMNS)

        latest_row = rows_desc[0] if rows_desc else None
        points = tuple(
            RuntimeFidelityTrendPoint(
                id=str(row["id"]),
                project_id=str(row["project_id"]),
                report_export_id=str(row["report_export_id"]) if row.get("report_export_id") else None,
                status=str(row.get("status") or "unknown"),
                official_api_records=int(row.get("official_api_records") or 0),
                browser_records=int(row.get("browser_records") or 0),
                comparable_prompt_city_pairs=int(row.get("comparable_prompt_city_pairs") or 0),
                mismatch_count=int(row.get("mismatch_count") or 0),
                difference_rate=float(row["difference_rate"]) if row.get("difference_rate") is not None else None,
                payload_hash=str(row["payload_hash"]) if row.get("payload_hash") else None,
                checked_at=str(row["checked_at"]) if row.get("checked_at") else None,
            )
            for row in reversed(rows_desc)
        )
        numeric_rates = [point.difference_rate for point in points if point.difference_rate is not None]
        earliest_rate = numeric_rates[0] if numeric_rates else None
        latest_rate = numeric_rates[-1] if numeric_rates else None
        if len(numeric_rates) < 2:
            trend_direction = "no_data" if not points else "insufficient_sampled_data"
        elif latest_rate is not None and earliest_rate is not None and latest_rate > earliest_rate:
            trend_direction = "worsening"
        elif latest_rate is not None and earliest_rate is not None and latest_rate < earliest_rate:
            trend_direction = "improving"
        else:
            trend_direction = "flat"

        return RuntimeFidelityTrend(
            project_id=project_id,
            report_export_id=report_export_id,
            total_count=total_count,
            sampled_count=sum(1 for point in points if point.status == "sampled"),
            limit=limit,
            latest_status=str(latest_row.get("status")) if latest_row else None,
            latest_checked_at=str(latest_row["checked_at"]) if latest_row and latest_row.get("checked_at") else None,
            earliest_checked_at=points[0].checked_at if points else None,
            latest_difference_rate=latest_rate,
            earliest_difference_rate=earliest_rate,
            average_difference_rate=round(sum(numeric_rates) / len(numeric_rates), 4) if numeric_rates else None,
            max_difference_rate=max(numeric_rates) if numeric_rates else None,
            trend_direction=trend_direction,
            points=points,
        )

    def create_runtime_fidelity_check(
        self,
        *,
        project_id: str,
        report_export_id: str | None = None,
        checked_by: str = "runtime-console",
    ) -> RuntimeFidelityCheck:
        project_id = project_id.strip()
        if not project_id:
            raise ValueError("project_id is required")
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            if not cursor.fetchone():
                raise ValueError("project not found")
            selected_report_id = report_export_id
            if selected_report_id:
                cursor.execute(
                    """
                    SELECT id
                    FROM report_exports
                    WHERE id = %s AND project_id = %s
                    LIMIT 1
                    """,
                    (_uuid(selected_report_id), _uuid(project_id)),
                )
                if not cursor.fetchone():
                    raise ValueError("report_export not found")
            else:
                cursor.execute(
                    """
                    SELECT id
                    FROM report_exports
                    WHERE project_id = %s
                    ORDER BY exported_at DESC, id DESC
                    LIMIT 1
                    """,
                    (_uuid(project_id),),
                )
                report_row = cursor.fetchone()
                selected_report_id = str(report_row["id"] if isinstance(report_row, dict) else report_row[0]) if report_row else None
            answer_run_rows = self._load_fidelity_answer_run_rows(
                cursor=cursor,
                project_id=project_id,
                report_export_id=selected_report_id,
            )
            check, audit_event = build_runtime_fidelity_check(
                project_id=project_id,
                report_export_id=selected_report_id,
                answer_run_rows=answer_run_rows,
                checked_by=checked_by.strip() or "runtime-console",
            )
            self.save_fidelity_check(check, audit_event, cursor=cursor)
            record = self._load_runtime_fidelity_check(cursor=cursor, fidelity_check=check)
        self.connection.commit()
        return record

    def save_fidelity_check(
        self,
        fidelity_check: dict[str, Any],
        audit_event: AuditEvent,
        *,
        cursor: DbCursor | None = None,
    ) -> None:
        owns_cursor = cursor is None
        active_cursor = cursor or self.connection.cursor()
        try:
            with active_cursor if owns_cursor else nullcontext(active_cursor) as current:
                current.execute(
                    """
                    INSERT INTO api_browser_fidelity_checks (
                      id, project_id, report_export_id, status, official_api_records,
                      browser_records, comparable_prompt_city_pairs, mismatch_count,
                      difference_rate, payload, payload_hash, answer_run_ids, checked_by, checked_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      status = EXCLUDED.status,
                      official_api_records = EXCLUDED.official_api_records,
                      browser_records = EXCLUDED.browser_records,
                      comparable_prompt_city_pairs = EXCLUDED.comparable_prompt_city_pairs,
                      mismatch_count = EXCLUDED.mismatch_count,
                      difference_rate = EXCLUDED.difference_rate,
                      payload = EXCLUDED.payload,
                      payload_hash = EXCLUDED.payload_hash,
                      answer_run_ids = EXCLUDED.answer_run_ids,
                      checked_by = EXCLUDED.checked_by,
                      checked_at = EXCLUDED.checked_at
                    """,
                    (
                        _uuid(str(fidelity_check["id"])),
                        _uuid(str(fidelity_check["project_id"])),
                        _uuid(str(fidelity_check["report_export_id"])) if fidelity_check.get("report_export_id") else None,
                        str(fidelity_check["status"]),
                        int(fidelity_check.get("official_api_records") or 0),
                        int(fidelity_check.get("browser_records") or 0),
                        int(fidelity_check.get("comparable_prompt_city_pairs") or 0),
                        int(fidelity_check.get("mismatch_count") or 0),
                        fidelity_check.get("difference_rate"),
                        _json_payload(fidelity_check.get("payload") or {}),
                        str(fidelity_check["payload_hash"]),
                        _uuid_array(tuple(str(value) for value in fidelity_check.get("answer_run_ids") or ())),
                        str(fidelity_check.get("checked_by") or "runtime-console"),
                        fidelity_check.get("checked_at"),
                    ),
                )
                self.save_audit_events((audit_event,), cursor=current)
        finally:
            if owns_cursor:
                self.connection.commit()

    def _load_fidelity_answer_run_rows(
        self,
        *,
        cursor: DbCursor,
        project_id: str,
        report_export_id: str | None,
    ) -> tuple[dict[str, Any], ...]:
        if report_export_id:
            cursor.execute(
                """
                SELECT answer_run_id
                FROM report_evidence
                WHERE report_export_id = %s
                ORDER BY created_at ASC
                """,
                (_uuid(report_export_id),),
            )
            answer_run_ids = tuple(str(row["answer_run_id"] if isinstance(row, dict) else row[0]) for row in cursor.fetchall())
            if not answer_run_ids:
                return ()
            filter_clause = "ar.id = ANY(%s::uuid[])"
            params: tuple[object, ...] = (_uuid_array(answer_run_ids),)
        else:
            filter_clause = "ar.project_id = %s"
            params = (_uuid(project_id),)
        cursor.execute(
            f"""
            SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                   count(*) FILTER (WHERE ea.asset_type = 'screenshot') AS screenshot_count,
                   count(*) FILTER (WHERE ea.asset_type = 'html_snapshot') AS html_snapshot_count
            FROM answer_runs ar
            LEFT JOIN evidence_assets ea ON ea.answer_run_id = ar.id
            WHERE {filter_clause}
            GROUP BY {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)}
            ORDER BY ar.collected_at ASC, ar.id ASC
            """,
            params,
        )
        return _rows_dict(cursor.fetchall(), ANSWER_RUN_COLUMNS + ("screenshot_count", "html_snapshot_count"))

    def _load_runtime_fidelity_check(
        self,
        *,
        cursor: DbCursor,
        fidelity_check: dict[str, Any],
    ) -> RuntimeFidelityCheck:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (_uuid(str(fidelity_check["project_id"])), "api_browser_fidelity_check", str(fidelity_check["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeFidelityCheck(fidelity_check=fidelity_check, audit_events=audit_events)

    def list_runtime_score_snapshots(
        self,
        *,
        project_id: str | None = None,
        scope_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeScoreSnapshotPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if scope_type:
            filters.append("scope_type = %s")
            params.append(scope_type)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM visibility_score_snapshots {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(VISIBILITY_SCORE_SNAPSHOT_COLUMNS)}
                FROM visibility_score_snapshots
                {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            snapshots = _rows_dict(cursor.fetchall(), VISIBILITY_SCORE_SNAPSHOT_COLUMNS)
            records = tuple(
                self._load_runtime_score_snapshot(
                    cursor=cursor,
                    snapshot=snapshot,
                    snapshot_id=str(snapshot["id"]),
                )
                for snapshot in snapshots
            )
        return RuntimeScoreSnapshotPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def export_runtime_score_snapshots_csv(
        self,
        *,
        project_id: str,
        scope_type: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        normalized_project_id = project_id.strip()
        if not normalized_project_id:
            raise ValueError("project_id is required")
        normalized_scope_type = scope_type.strip() if scope_type else None
        page = self.list_runtime_score_snapshots(
            project_id=normalized_project_id,
            scope_type=normalized_scope_type,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_score_snapshots_csv(page)
        row_count = sum(max(1, len(record.contributions)) for record in page.records)
        filters = {
            "project_id": normalized_project_id,
            "scope_type": normalized_scope_type,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_score_snapshots_csv",
            filename="runtime-score-snapshots.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=page.total_count,
            row_count=row_count,
        )

    def list_runtime_citation_graphs(
        self,
        *,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeCitationGraphPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        params: list[object] = []
        where_clause = ""
        if project_id:
            where_clause = "WHERE project_id = %s"
            params.append(_uuid(project_id))

        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(DISTINCT project_id) FROM source_graphs {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT project_id
                FROM source_graphs
                {where_clause}
                GROUP BY project_id
                ORDER BY max(created_at) DESC, project_id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            project_rows = cursor.fetchall()
            project_ids = tuple(str(row["project_id"] if isinstance(row, dict) else row[0]) for row in project_rows)
            records = tuple(
                self._load_runtime_citation_graph(cursor=cursor, project_id=graph_project_id)
                for graph_project_id in project_ids
            )
        return RuntimeCitationGraphPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def export_runtime_citation_graphs_csv(
        self,
        *,
        project_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        normalized_project_id = project_id.strip()
        if not normalized_project_id:
            raise ValueError("project_id is required")
        page = self.list_runtime_citation_graphs(
            project_id=normalized_project_id,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_citation_graphs_csv(page)
        row_count = sum(max(1, len(record.nodes)) for record in page.records)
        filters = {
            "project_id": normalized_project_id,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_citation_graphs_csv",
            filename="runtime-citation-graphs.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters=filters,
            total_count=page.total_count,
            row_count=row_count,
        )

    def list_runtime_report_exports(
        self,
        *,
        project_id: str | None = None,
        report_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeReportExportPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if report_type:
            filters.append("report_type = %s")
            params.append(report_type)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM report_exports {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(REPORT_EXPORT_COLUMNS)}
                FROM report_exports
                {where_clause}
                ORDER BY exported_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            reports = _rows_dict(cursor.fetchall(), REPORT_EXPORT_COLUMNS)
            records = tuple(
                self._load_runtime_report_export(cursor=cursor, report_export=report)
                for report in reports
            )
        return RuntimeReportExportPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def export_runtime_report_management_events_csv(
        self,
        *,
        project_id: str,
        status: str | None = None,
        report_type: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        project_id = project_id.strip()
        normalized_status = status.strip().lower() if status else None
        normalized_report_type = report_type.strip() if report_type else None
        if not project_id:
            raise ValueError("project_id is required")
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters = ["re.project_id = %s", "ae.event_type = %s"]
        params: list[object] = [_uuid(project_id), "report_export_management_recorded"]
        if normalized_status:
            filters.append("ae.input_refs->'status' ? %s")
            params.append(normalized_status)
        if normalized_report_type:
            filters.append("re.report_type = %s")
            params.append(normalized_report_type)
        where_clause = f"WHERE {' AND '.join(filters)}"
        report_columns = ", ".join(f"re.{column}" for column in REPORT_EXPORT_COLUMNS)
        audit_columns = ", ".join(f"ae.{column} AS management_{column}" for column in AUDIT_EVENT_COLUMNS)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*)
                FROM report_exports re
                JOIN audit_events ae ON ae.target_type = %s
                  AND ae.target_id = re.id::text
                {where_clause}
                """,
                ("report_export", *params),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {report_columns}, {audit_columns}
                FROM report_exports re
                JOIN audit_events ae ON ae.target_type = %s
                  AND ae.target_id = re.id::text
                {where_clause}
                ORDER BY ae.created_at DESC, re.exported_at DESC, re.id DESC
                LIMIT %s OFFSET %s
                """,
                ("report_export", *params, limit, offset),
            )
            rows = cursor.fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            columns = (*REPORT_EXPORT_COLUMNS, *(f"management_{column}" for column in AUDIT_EVENT_COLUMNS))
            source = row if isinstance(row, dict) else dict(zip(columns, row, strict=False))
            report_export = {column: source.get(column) for column in REPORT_EXPORT_COLUMNS}
            management_event = {
                column: source.get(f"management_{column}", source.get(column)) for column in AUDIT_EVENT_COLUMNS
            }
            records.append({**report_export, "management_event": management_event})
        content = _render_runtime_report_management_events_csv(tuple(records))
        filters_payload = {
            "project_id": project_id,
            "status": normalized_status,
            "report_type": normalized_report_type,
            "limit": limit,
            "offset": offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_report_management_events_csv",
            filename="runtime-report-management-events.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters_payload.items() if value is not None},
            total_count=total_count,
            row_count=len(records),
        )

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
    ) -> RuntimeReportArtifact | None:
        artifact_type = artifact_type.lower()
        if artifact_type not in {"markdown", "csv", "pdf"}:
            raise ValueError("artifact_type must be markdown, csv, or pdf")
        template_name = (template or "standard").strip().lower() or "standard"
        if template_name not in {"standard", "white_label"}:
            raise ValueError("template must be standard or white_label")
        if template_name == "white_label" and artifact_type != "pdf":
            raise ValueError("white_label template is only supported for pdf artifacts")
        brand_kit: dict[str, Any] | None = None
        with self.connection.cursor() as cursor:
            report_export = self._load_report_export_by_id(
                cursor=cursor,
                report_export_id=report_export_id,
            )
            if not report_export:
                return None
            runtime_report = self._load_runtime_report_export(
                cursor=cursor,
                report_export=report_export,
            )
            if template_name == "white_label" and (not client_name or not prepared_by):
                cursor.execute(
                    f"""
                    SELECT {", ".join(PROJECT_BRAND_KIT_COLUMNS)}
                    FROM project_brand_kits
                    WHERE project_id = %s
                    LIMIT 1
                    """,
                    (_uuid(str(runtime_report.report_export["project_id"])),),
                )
                brand_kit_row = cursor.fetchone()
                brand_kit = _row_dict(brand_kit_row, PROJECT_BRAND_KIT_COLUMNS) if brand_kit_row else None
        white_label_client = (
            client_name
            or (brand_kit.get("client_name") if brand_kit else None)
            or "Client"
        ).strip() or "Client"
        white_label_prepared_by = (
            prepared_by
            or (brand_kit.get("prepared_by") if brand_kit else None)
            or "GENO SaaS"
        ).strip() or "GENO SaaS"
        white_label_logo_url = (brand_kit.get("logo_url") if brand_kit else None) or None
        white_label_primary_color = (brand_kit.get("primary_color") if brand_kit else None) or None
        white_label_secondary_color = (brand_kit.get("secondary_color") if brand_kit else None) or None
        white_label_footer_text = (brand_kit.get("footer_text") if brand_kit else None) or None
        filtered_answer_runs, sort_key = _filter_runtime_report_answer_runs(
            runtime_report.answer_runs,
            platform=platform,
            city=city,
            intent_type=intent_type,
            status=status,
            sort=sort,
        )
        filtered_report = RuntimeReportExport(
            report_export=runtime_report.report_export,
            score_snapshots=runtime_report.score_snapshots,
            answer_runs=filtered_answer_runs,
            citation_graph=runtime_report.citation_graph,
            audit_events=runtime_report.audit_events,
        )
        if artifact_type == "markdown":
            content = _render_runtime_report_markdown(filtered_report)
            extension = "md"
            media_type = "text/markdown; charset=utf-8"
        elif artifact_type == "csv":
            content = _render_runtime_report_csv(filtered_report)
            extension = "csv"
            media_type = "text/csv; charset=utf-8"
        else:
            markdown = (
                _render_white_label_report_markdown(
                    filtered_report,
                    client_name=white_label_client,
                    prepared_by=white_label_prepared_by,
                    logo_url=white_label_logo_url,
                    primary_color=white_label_primary_color,
                    secondary_color=white_label_secondary_color,
                    footer_text=white_label_footer_text,
                )
                if template_name == "white_label"
                else _render_runtime_report_markdown(filtered_report)
            )
            content = render_markdown_pdf(markdown)
            extension = "pdf"
            media_type = "application/pdf"
        template_payload = (
            {
                "template": template_name,
                "client_name": white_label_client,
                "prepared_by": white_label_prepared_by,
                "logo_url": white_label_logo_url,
                "primary_color": white_label_primary_color,
                "secondary_color": white_label_secondary_color,
                "footer_text": white_label_footer_text,
                "source": "project_brand_kit" if brand_kit else "query_or_default",
            }
            if template_name == "white_label"
            else {"template": template_name}
        )
        filters = {
            "platform": platform,
            "city": city,
            "intent_type": intent_type,
            "status": status,
        }
        active_filters = {key: value for key, value in filters.items() if value is not None}
        filename_stem = report_export["report_version"]
        if template_name == "white_label":
            filename_stem = f"{filename_stem}-white-label"
        filename = f"{filename_stem}.{extension}"
        return RuntimeReportArtifact(
            report_export=report_export,
            artifact_type=artifact_type,
            template=template_name,
            template_payload=template_payload,
            template_hash=_artifact_hash(json.dumps(template_payload, ensure_ascii=False, sort_keys=True)),
            filename=filename,
            media_type=media_type,
            content=content,
            content_hash=_artifact_hash(content),
            filters=active_filters,
            filter_hash=_artifact_hash(json.dumps(active_filters, ensure_ascii=False, sort_keys=True)),
            sort=sort_key,
            total_count=len(runtime_report.answer_runs),
            row_count=len(filtered_report.answer_runs),
        )

    def enqueue_runtime_report_export_job(
        self,
        job: RuntimeReportExportJobInput,
    ) -> RuntimeReportExportJob:
        project_id = job.project_id.strip()
        report_export_id = job.report_export_id.strip() if job.report_export_id else None
        artifact_type = job.artifact_type.strip().lower()
        template = job.template.strip().lower() or "standard"
        sort = job.sort.strip() or "collected_at_desc"
        requested_by = job.requested_by.strip()
        reason = job.reason.strip() if job.reason else None
        if not project_id:
            raise ValueError("project_id is required")
        if artifact_type not in {"markdown", "csv", "pdf"}:
            raise ValueError("artifact_type must be markdown, csv, or pdf")
        if template not in {"standard", "white_label"}:
            raise ValueError("template must be standard or white_label")
        if template == "white_label" and artifact_type != "pdf":
            raise ValueError("white_label template is only supported for pdf artifacts")
        if not requested_by:
            raise ValueError("requested_by is required")
        filters = _json_compatible(job.filters or {})
        if not isinstance(filters, dict):
            raise ValueError("filters must be an object")
        job_id = _stable_id(
            "report-export-job",
            project_id,
            report_export_id or "latest",
            artifact_type,
            template,
            json.dumps(filters, ensure_ascii=False, sort_keys=True),
            sort,
            requested_by,
            datetime.now(UTC).isoformat(),
        )
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM projects WHERE id = %s LIMIT 1",
                (_uuid(project_id),),
            )
            if not cursor.fetchone():
                raise ValueError("project not found")
            report_export: dict[str, Any] | None = None
            if report_export_id:
                report_export = self._load_report_export_by_id(
                    cursor=cursor,
                    report_export_id=report_export_id,
                )
                if not report_export:
                    raise ValueError("report_export not found")
                if str(report_export["project_id"]) != project_id:
                    raise ValueError("report_export does not belong to project")
            cursor.execute(
                f"""
                INSERT INTO report_export_jobs (
                  id, project_id, report_export_id, status, artifact_type, template,
                  filters, sort, requested_by, requested_at, max_attempts, updated_by, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {REPORT_EXPORT_JOB_RETURNING}
                """,
                (
                    _uuid(job_id),
                    _uuid(project_id),
                    _uuid(report_export_id),
                    "queued",
                    artifact_type,
                    template,
                    _json_payload(filters),
                    sort,
                    requested_by,
                    datetime.now(UTC),
                    3,
                    requested_by,
                    datetime.now(UTC),
                ),
            )
            saved_job = _row_dict(cursor.fetchone(), REPORT_EXPORT_JOB_COLUMNS)
            audit_event = build_audit_event(
                event_type="report_export_job_queued",
                project_id=project_id,
                actor_type="user",
                actor_id=requested_by,
                target_type="report_export_job",
                target_id=job_id,
                before=None,
                after=saved_job,
                input_refs={
                    "project_ids": [project_id],
                    "report_export_ids": [report_export_id] if report_export_id else [],
                    "artifact_type": [artifact_type],
                    "template": [template],
                    "sort": [sort],
                    "filters": [filters],
                },
                output_refs={
                    "report_export_job_ids": [job_id],
                    "status": ["queued"],
                },
                method_version="runtime_report_export_job_v1",
                reason=reason or "enqueue report export artifact job",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            record = self._runtime_report_export_job_from_row(cursor=cursor, row=saved_job)
        self.connection.commit()
        return record

    def list_runtime_report_export_jobs(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        report_export_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeReportExportJobPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id.strip()))
        if status:
            filters.append("status = %s")
            params.append(status.strip().lower())
        if report_export_id:
            filters.append("report_export_id = %s")
            params.append(_uuid(report_export_id.strip()))
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM report_export_jobs {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(REPORT_EXPORT_JOB_COLUMNS)}
                FROM report_export_jobs
                {where_clause}
                ORDER BY requested_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = _rows_dict(cursor.fetchall(), REPORT_EXPORT_JOB_COLUMNS)
            records = tuple(self._runtime_report_export_job_from_row(cursor=cursor, row=row) for row in rows)
        return RuntimeReportExportJobPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def export_runtime_report_export_jobs_csv(
        self,
        *,
        project_id: str,
        status: str | None = None,
        report_export_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        page = self.list_runtime_report_export_jobs(
            project_id=project_id,
            status=status,
            report_export_id=report_export_id,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_report_export_jobs_csv(page)
        filters = {
            "project_id": project_id.strip(),
            "status": status.strip().lower() if status else None,
            "report_export_id": report_export_id.strip() if report_export_id else None,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_report_export_jobs_csv",
            filename="runtime-report-export-jobs.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=page.total_count,
            row_count=len(page.records),
        )

    def get_runtime_report_export_job_queue_stats(
        self,
        *,
        project_id: str | None = None,
    ) -> RuntimeReportExportJobQueueStats:
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id.strip()))
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM report_export_jobs {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT status, count(*)::int AS count
                FROM report_export_jobs
                {where_clause}
                GROUP BY status
                ORDER BY status ASC
                """,
                tuple(params),
            )
            status_rows = _rows_dict(cursor.fetchall(), ("status", "count"))
            status_counts = {str(row["status"]): int(row["count"]) for row in status_rows}
            cursor.execute(
                f"""
                SELECT
                  count(*) FILTER (
                    WHERE status = 'queued'
                      AND attempt_count < max_attempts
                      AND (next_attempt_at IS NULL OR next_attempt_at <= now())
                  )::int AS retryable_count,
                  count(*) FILTER (
                    WHERE status = 'running'
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at <= now()
                  )::int AS expired_running_count,
                  count(*) FILTER (
                    WHERE status IN ('queued', 'running', 'failed', 'dead_letter')
                      AND attempt_count >= max_attempts
                  )::int AS max_attempts_reached_count,
                  min(requested_at) FILTER (WHERE status = 'queued') AS oldest_queued_at
                FROM report_export_jobs
                {where_clause}
                """,
                tuple(params),
            )
            stats_row = _row_dict(
                cursor.fetchone(),
                (
                    "retryable_count",
                    "expired_running_count",
                    "max_attempts_reached_count",
                    "oldest_queued_at",
                ),
            )
        return RuntimeReportExportJobQueueStats(
            total_count=total_count,
            status_counts=status_counts,
            retryable_count=int(stats_row.get("retryable_count") or 0),
            expired_running_count=int(stats_row.get("expired_running_count") or 0),
            max_attempts_reached_count=int(stats_row.get("max_attempts_reached_count") or 0),
            oldest_queued_at=stats_row.get("oldest_queued_at"),
            generated_at=datetime.now(UTC),
        )

    def list_runtime_notifications(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        notification_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeNotificationPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id.strip()))
        if status:
            filters.append("status = %s")
            params.append(status.strip().lower())
        if notification_type:
            filters.append("notification_type = %s")
            params.append(notification_type.strip().lower())
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        unread_filters: list[str] = []
        unread_params: list[object] = []
        if project_id:
            unread_filters.append("project_id = %s")
            unread_params.append(_uuid(project_id.strip()))
        if notification_type:
            unread_filters.append("notification_type = %s")
            unread_params.append(notification_type.strip().lower())
        unread_where_clause = f"WHERE {' AND '.join([*unread_filters, 'status = %s'])}" if unread_filters else "WHERE status = %s"
        unread_params.append("unread")
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM runtime_notifications {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(f"SELECT count(*) FROM runtime_notifications {unread_where_clause}", tuple(unread_params))
            unread_row = cursor.fetchone()
            unread_count = int(unread_row[0] if not isinstance(unread_row, dict) else unread_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_COLUMNS)}
                FROM runtime_notifications
                {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = _rows_dict(cursor.fetchall(), RUNTIME_NOTIFICATION_COLUMNS)
            records = tuple(self._runtime_notification_from_row(cursor=cursor, row=row) for row in rows)
        return RuntimeNotificationPage(
            total_count=total_count,
            unread_count=unread_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def export_runtime_notifications_csv(
        self,
        *,
        project_id: str,
        status: str | None = None,
        notification_type: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        page = self.list_runtime_notifications(
            project_id=project_id,
            status=status,
            notification_type=notification_type,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_notifications_csv(page)
        filters = {
            "project_id": project_id.strip(),
            "status": status.strip().lower() if status else None,
            "notification_type": notification_type.strip().lower() if notification_type else None,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_notifications_csv",
            filename="runtime-notifications.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=page.total_count,
            row_count=len(page.records),
        )

    def update_runtime_notification_status(
        self,
        update: RuntimeNotificationStatusInput,
    ) -> RuntimeNotification:
        notification_id = update.notification_id.strip()
        status = update.status.strip().lower()
        updated_by = update.updated_by.strip() or "runtime-console"
        reason = update.reason.strip() if update.reason else None
        if not notification_id:
            raise ValueError("notification_id is required")
        if status not in {"unread", "read"}:
            raise ValueError("notification status must be unread or read")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_COLUMNS)}
                FROM runtime_notifications
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(notification_id),),
            )
            before = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_COLUMNS)
            if not before:
                raise ValueError("runtime notification not found")
            now = datetime.now(UTC)
            cursor.execute(
                f"""
                UPDATE runtime_notifications
                SET status = %s,
                    read_at = CASE WHEN %s = 'read' THEN COALESCE(read_at, %s) ELSE NULL END,
                    updated_by = %s,
                    updated_at = %s
                WHERE id = %s
                RETURNING {", ".join(RUNTIME_NOTIFICATION_COLUMNS)}
                """,
                (status, status, now, updated_by, now, _uuid(notification_id)),
            )
            after = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_COLUMNS)
            audit_event = build_audit_event(
                event_type="runtime_notification_status_updated",
                project_id=str(after["project_id"]),
                actor_type="user",
                actor_id=updated_by,
                target_type="runtime_notification",
                target_id=notification_id,
                before=before,
                after=after,
                input_refs={
                    "runtime_notification_ids": [notification_id],
                    "status": [status],
                },
                output_refs={
                    "runtime_notification_ids": [notification_id],
                    "status": [status],
                },
                method_version="runtime_notification_status_v1",
                reason=reason or f"mark runtime notification {status}",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            record = self._runtime_notification_from_row(cursor=cursor, row=after)
        self.connection.commit()
        return record

    def save_runtime_notification_subscription(
        self,
        subscription: RuntimeNotificationSubscriptionInput,
    ) -> RuntimeNotificationSubscription:
        project_id = subscription.project_id.strip()
        channel = subscription.channel.strip().lower() if subscription.channel else "webhook"
        endpoint_url = subscription.endpoint_url.strip()
        event_types = tuple(
            event_type.strip().lower()
            for event_type in subscription.event_types
            if event_type and event_type.strip()
        )
        severity_threshold = subscription.severity_threshold.strip().lower() if subscription.severity_threshold else "info"
        status = subscription.status.strip().lower() if subscription.status else "active"
        updated_by = subscription.updated_by.strip() or "runtime-console"
        reason = subscription.reason.strip() if subscription.reason else None
        if not project_id:
            raise ValueError("project_id is required")
        if channel not in RUNTIME_NOTIFICATION_SUBSCRIPTION_CHANNELS:
            raise ValueError("notification subscription channel must be webhook, slack, or email")
        if not endpoint_url:
            raise ValueError("endpoint_url is required")
        parsed_url = urlparse(endpoint_url)
        if channel == "email":
            if parsed_url.scheme != "mailto" or not _runtime_notification_email_recipients(endpoint_url):
                raise ValueError("email notification endpoint_url must be a mailto URL with at least one recipient")
        elif parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("endpoint_url must be an http or https URL")
        if not event_types:
            raise ValueError("event_types must contain at least one event type")
        if severity_threshold not in RUNTIME_NOTIFICATION_SEVERITY_ORDER:
            raise ValueError("severity_threshold must be info, warning, or critical")
        if status not in {"active", "paused", "disabled"}:
            raise ValueError("subscription status must be active, paused, or disabled")
        subscription_id = _stable_id("runtime-notification-subscription", project_id, channel, endpoint_url)
        metadata = _json_compatible(subscription.metadata or {})
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s LIMIT 1", (_uuid(project_id),))
            if not cursor.fetchone():
                raise ValueError("project not found")
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)}
                FROM runtime_notification_subscriptions
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(subscription_id),),
            )
            existing_row = cursor.fetchone()
            before = (
                _row_dict(existing_row, RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)
                if existing_row
                else None
            )
            cursor.execute(
                f"""
                INSERT INTO runtime_notification_subscriptions (
                  id, project_id, channel, endpoint_url, event_types, severity_threshold,
                  status, metadata, created_by, updated_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id, channel, endpoint_url) DO UPDATE SET
                  event_types = EXCLUDED.event_types,
                  severity_threshold = EXCLUDED.severity_threshold,
                  status = EXCLUDED.status,
                  metadata = EXCLUDED.metadata,
                  updated_by = EXCLUDED.updated_by,
                  updated_at = now()
                RETURNING {", ".join(RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)}
                """,
                (
                    _uuid(subscription_id),
                    _uuid(project_id),
                    channel,
                    endpoint_url,
                    list(event_types),
                    severity_threshold,
                    status,
                    _json_payload(metadata),
                    updated_by,
                    updated_by,
                ),
            )
            after = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)
            subscription_output_refs = {
                "runtime_notification_subscription_ids": [str(after["id"])],
                "status": [status],
            }
            if channel == "email":
                email_metadata = _runtime_notification_email_metadata(after)
                control_hashes = _runtime_notification_email_control_hashes(
                    _runtime_notification_email_control_metadata(email_metadata)
                )
                reply_to = _metadata_header_value(email_metadata, "email_reply_to")
                suppression_hashes = list(_runtime_notification_configured_suppression_hashes(email_metadata))
                subscription_output_refs.update(
                    {
                        "email_control_hashes": [
                            f"{key}:{value}"
                            for key, value in sorted(control_hashes.items())
                            if value
                        ],
                        "email_reply_to_hashes": [runtime_email_body_hash(reply_to)] if reply_to else [],
                        "email_suppression_hashes": suppression_hashes,
                    }
                )
            audit_event = build_audit_event(
                event_type="runtime_notification_subscription_saved",
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="runtime_notification_subscription",
                target_id=str(after["id"]),
                before=before,
                after=after,
                input_refs={
                    "project_ids": [project_id],
                    "channel": [channel],
                    "event_types": list(event_types),
                },
                output_refs=subscription_output_refs,
                method_version="runtime_notification_subscription_v1",
                reason=reason or f"save runtime notification {channel} subscription",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            record = self._runtime_notification_subscription_from_row(cursor=cursor, row=after)
        self.connection.commit()
        return record

    def list_runtime_notification_subscriptions(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeNotificationSubscriptionPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id.strip()))
        if status:
            filters.append("status = %s")
            params.append(status.strip().lower())
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM runtime_notification_subscriptions {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)}
                FROM runtime_notification_subscriptions
                {where_clause}
                ORDER BY updated_at DESC, created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = _rows_dict(cursor.fetchall(), RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)
            records = tuple(self._runtime_notification_subscription_from_row(cursor=cursor, row=row) for row in rows)
        return RuntimeNotificationSubscriptionPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def export_runtime_notification_subscriptions_csv(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        page = self.list_runtime_notification_subscriptions(
            project_id=project_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_notification_subscriptions_csv(page)
        filters = {
            "project_id": project_id.strip(),
            "status": status.strip().lower() if status else None,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_notification_subscriptions_csv",
            filename="runtime-notification-subscriptions.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=page.total_count,
            row_count=len(page.records),
        )

    def list_runtime_notification_deliveries(
        self,
        *,
        project_id: str | None = None,
        notification_id: str | None = None,
        subscription_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeNotificationDeliveryPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id.strip()))
        if notification_id:
            filters.append("notification_id = %s")
            params.append(_uuid(notification_id.strip()))
        if subscription_id:
            filters.append("subscription_id = %s")
            params.append(_uuid(subscription_id.strip()))
        if status:
            filters.append("status = %s")
            params.append(status.strip().lower())
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM runtime_notification_deliveries {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_DELIVERY_COLUMNS)}
                FROM runtime_notification_deliveries
                {where_clause}
                ORDER BY updated_at DESC, created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = _rows_dict(cursor.fetchall(), RUNTIME_NOTIFICATION_DELIVERY_COLUMNS)
            records = tuple(self._runtime_notification_delivery_from_row(cursor=cursor, row=row) for row in rows)
        return RuntimeNotificationDeliveryPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def export_runtime_notification_deliveries_csv(
        self,
        *,
        project_id: str,
        notification_id: str | None = None,
        subscription_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        page = self.list_runtime_notification_deliveries(
            project_id=project_id,
            notification_id=notification_id,
            subscription_id=subscription_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_notification_deliveries_csv(page)
        filters = {
            "project_id": project_id.strip(),
            "notification_id": notification_id.strip() if notification_id else None,
            "subscription_id": subscription_id.strip() if subscription_id else None,
            "status": status.strip().lower() if status else None,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_notification_deliveries_csv",
            filename="runtime-notification-deliveries.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=page.total_count,
            row_count=len(page.records),
        )

    def list_runtime_notification_email_feedback_events(
        self,
        *,
        project_id: str | None = None,
        delivery_id: str | None = None,
        notification_id: str | None = None,
        subscription_id: str | None = None,
        feedback_type: str | None = None,
        provider: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeNotificationEmailFeedbackPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id.strip()))
        if delivery_id:
            filters.append("delivery_id = %s")
            params.append(_uuid(delivery_id.strip()))
        if notification_id:
            filters.append("notification_id = %s")
            params.append(_uuid(notification_id.strip()))
        if subscription_id:
            filters.append("subscription_id = %s")
            params.append(_uuid(subscription_id.strip()))
        if feedback_type:
            filters.append("feedback_type = %s")
            params.append(feedback_type.strip().lower())
        if provider:
            filters.append("provider = %s")
            params.append(" ".join(provider.replace("\r", "\n").split()).strip())
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"SELECT count(*) FROM runtime_notification_email_feedback_events {where_clause}",
                tuple(params),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_COLUMNS)}
                FROM runtime_notification_email_feedback_events
                {where_clause}
                ORDER BY occurred_at DESC, created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = _rows_dict(cursor.fetchall(), RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_COLUMNS)
            records = tuple(
                self._runtime_notification_email_feedback_from_row(cursor=cursor, feedback_event=row)
                for row in rows
            )
        return RuntimeNotificationEmailFeedbackPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def claim_next_runtime_notification_delivery(
        self,
        *,
        updated_by: str = "notification-worker",
        lease_seconds: int = 300,
    ) -> RuntimeNotificationDelivery | None:
        updated_by = updated_by.strip() or "notification-worker"
        lease_seconds = max(1, int(lease_seconds))
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_DELIVERY_COLUMNS)}
                FROM runtime_notification_deliveries
                WHERE (
                  (status = %s AND (next_attempt_at IS NULL OR next_attempt_at <= now()))
                  OR (status = %s AND lease_expires_at IS NOT NULL AND lease_expires_at <= now())
                )
                  AND attempt_count < max_attempts
                ORDER BY
                  CASE WHEN status = %s THEN 0 ELSE 1 END,
                  COALESCE(next_attempt_at, created_at) ASC,
                  created_at ASC,
                  id ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                ("queued", "sending", "queued"),
            )
            before = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_DELIVERY_COLUMNS)
            if not before:
                return None
            now = datetime.now(UTC)
            lease_expires_at = now + timedelta(seconds=lease_seconds)
            cursor.execute(
                f"""
                UPDATE runtime_notification_deliveries
                SET status = %s,
                    attempt_count = attempt_count + 1,
                    lease_expires_at = %s,
                    next_attempt_at = NULL,
                    updated_by = %s,
                    updated_at = %s
                WHERE id = %s AND status = %s
                RETURNING {RUNTIME_NOTIFICATION_DELIVERY_RETURNING}
                """,
                ("sending", lease_expires_at, updated_by, now, _uuid(str(before["id"])), str(before["status"])),
            )
            after = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_DELIVERY_COLUMNS)
            if not after:
                self.connection.rollback()
                return None
            delivery_id = str(after["id"])
            audit_event = build_audit_event(
                event_type="runtime_notification_delivery_status_updated",
                project_id=str(after["project_id"]),
                actor_type="worker",
                actor_id=updated_by,
                target_type="runtime_notification_delivery",
                target_id=delivery_id,
                before=before,
                after=after,
                input_refs={
                    "runtime_notification_delivery_ids": [delivery_id],
                    "status": ["sending"],
                },
                output_refs={
                    "runtime_notification_delivery_ids": [delivery_id],
                    "claimed": [True],
                },
                method_version="runtime_notification_delivery_claim_v1",
                reason="claim runtime notification delivery",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            record = self._runtime_notification_delivery_from_row(cursor=cursor, row=after)
        self.connection.commit()
        return record

    def update_runtime_notification_delivery_status(
        self,
        update: RuntimeNotificationDeliveryStatusInput,
    ) -> RuntimeNotificationDelivery:
        delivery_id = update.delivery_id.strip()
        status = update.status.strip().lower()
        updated_by = update.updated_by.strip() or "notification-worker"
        response_body_hash = update.response_body_hash.strip() if update.response_body_hash else None
        error_message = update.error_message.strip() if update.error_message else None
        reason = update.reason.strip() if update.reason else None
        allowed_statuses = {"queued", "sending", "delivered", "failed", "dead_letter", "cancelled"}
        if not delivery_id:
            raise ValueError("delivery_id is required")
        if status not in allowed_statuses:
            raise ValueError("delivery status must be queued, sending, delivered, failed, dead_letter, or cancelled")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_DELIVERY_COLUMNS)}
                FROM runtime_notification_deliveries
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(delivery_id),),
            )
            before = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_DELIVERY_COLUMNS)
            if not before:
                raise ValueError("runtime notification delivery not found")
            now = datetime.now(UTC)
            cursor.execute(
                f"""
                UPDATE runtime_notification_deliveries
                SET status = %s,
                    lease_expires_at = CASE WHEN %s = 'sending' THEN COALESCE(%s, lease_expires_at) ELSE NULL END,
                    next_attempt_at = %s,
                    response_status = %s,
                    response_body_hash = %s,
                    error_message = %s,
                    updated_by = %s,
                    updated_at = %s
                WHERE id = %s
                RETURNING {RUNTIME_NOTIFICATION_DELIVERY_RETURNING}
                """,
                (
                    status,
                    status,
                    update.lease_expires_at,
                    update.next_attempt_at,
                    update.response_status,
                    response_body_hash,
                    error_message,
                    updated_by,
                    now,
                    _uuid(delivery_id),
                ),
            )
            after = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_DELIVERY_COLUMNS)
            audit_event = build_audit_event(
                event_type="runtime_notification_delivery_status_updated",
                project_id=str(after["project_id"]),
                actor_type="worker" if updated_by == "notification-worker" else "user",
                actor_id=updated_by,
                target_type="runtime_notification_delivery",
                target_id=delivery_id,
                before=before,
                after=after,
                input_refs={
                    "runtime_notification_delivery_ids": [delivery_id],
                    "status": [status],
                },
                output_refs={
                    "runtime_notification_delivery_ids": [delivery_id],
                    "response_status": [str(update.response_status)] if update.response_status is not None else [],
                },
                method_version="runtime_notification_delivery_status_v1",
                reason=reason or f"mark runtime notification delivery {status}",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            record = self._runtime_notification_delivery_from_row(cursor=cursor, row=after)
        self.connection.commit()
        return record

    def record_runtime_notification_email_feedback(
        self,
        feedback: RuntimeNotificationEmailFeedbackInput,
    ) -> RuntimeNotificationEmailFeedback:
        delivery_id = feedback.delivery_id.strip()
        feedback_type = feedback.feedback_type.strip().lower()
        recorded_by = feedback.recorded_by.strip() or "runtime-console"
        actor_type = "user"
        if recorded_by == "notification-worker":
            actor_type = "worker"
        elif recorded_by == "email-feedback-webhook":
            actor_type = "system"
        reason = feedback.reason.strip() if feedback.reason else None
        provider = " ".join(str(feedback.provider or "").replace("\r", "\n").split()).strip() or None
        recipient = _normalize_runtime_email_address(feedback.recipient) if feedback.recipient else ""
        recipient_hash = runtime_email_body_hash(recipient) if recipient else _sha256_hex_or_none(
            feedback.recipient_hash,
            field_name="recipient_hash",
        )
        provider_event_id = " ".join(str(feedback.provider_event_id or "").replace("\r", "\n").split()).strip()
        provider_event_id_hash = runtime_email_body_hash(provider_event_id) if provider_event_id else _sha256_hex_or_none(
            feedback.provider_event_id_hash,
            field_name="provider_event_id_hash",
        )
        occurred_at = feedback.occurred_at or datetime.now(UTC)
        metadata = _json_compatible(feedback.metadata or {})
        if not delivery_id:
            raise ValueError("delivery_id is required")
        if feedback_type not in RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_TYPES:
            raise ValueError("email feedback type must be bounce, complaint, unsubscribe, or suppressed")
        if not recipient_hash and not provider_event_id_hash:
            raise ValueError("email feedback requires recipient, recipient_hash, provider_event_id, or provider_event_id_hash")
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_DELIVERY_COLUMNS)}
                FROM runtime_notification_deliveries
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(delivery_id),),
            )
            delivery = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_DELIVERY_COLUMNS)
            if not delivery:
                raise ValueError("runtime notification delivery not found")
            if str(delivery.get("channel") or "").strip().lower() != "email":
                raise ValueError("email feedback can only be recorded for email runtime notification deliveries")
            if provider_event_id_hash:
                cursor.execute(
                    f"""
                    SELECT {", ".join(RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_COLUMNS)}
                    FROM runtime_notification_email_feedback_events
                    WHERE delivery_id = %s
                      AND feedback_type = %s
                      AND provider_event_id_hash = %s
                    ORDER BY occurred_at DESC, created_at DESC, id DESC
                    LIMIT 1
                    """,
                    (_uuid(delivery_id), feedback_type, provider_event_id_hash),
                )
                existing_feedback_event = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_COLUMNS)
                if existing_feedback_event:
                    audit_event = build_audit_event(
                        event_type="runtime_notification_email_feedback_duplicate_ignored",
                        project_id=str(delivery["project_id"]),
                        actor_type=actor_type,
                        actor_id=recorded_by,
                        target_type="runtime_notification_delivery",
                        target_id=delivery_id,
                        before=delivery,
                        after=existing_feedback_event,
                        input_refs={
                            "runtime_notification_delivery_ids": [delivery_id],
                            "feedback_type": [feedback_type],
                            "provider_event_id_hashes": [provider_event_id_hash],
                            "recipient_hashes": [recipient_hash] if recipient_hash else [],
                        },
                        output_refs={
                            "runtime_notification_email_feedback_event_ids": [str(existing_feedback_event["id"])],
                            "runtime_notification_delivery_ids": [delivery_id],
                            "runtime_notification_ids": [str(delivery["notification_id"])],
                            "runtime_notification_subscription_ids": [str(delivery["subscription_id"])],
                            "duplicate_ignored": [True],
                        },
                        method_version="runtime_notification_email_feedback_idempotency_v1",
                        reason=reason or f"ignore duplicate runtime notification email {feedback_type} feedback",
                    )
                    self.save_audit_events((audit_event,), cursor=cursor)
                    record = self._runtime_notification_email_feedback_from_row(
                        cursor=cursor,
                        feedback_event=existing_feedback_event,
                        delivery=delivery,
                    )
                    self.connection.commit()
                    return record
            cursor.execute(
                f"""
                INSERT INTO runtime_notification_email_feedback_events (
                  project_id, delivery_id, notification_id, subscription_id, feedback_type,
                  recipient_hash, provider, provider_event_id_hash, occurred_at, metadata, recorded_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_RETURNING}
                """,
                (
                    _uuid(str(delivery["project_id"])),
                    _uuid(str(delivery["id"])),
                    _uuid(str(delivery["notification_id"])),
                    _uuid(str(delivery["subscription_id"])),
                    feedback_type,
                    recipient_hash,
                    provider,
                    provider_event_id_hash,
                    occurred_at,
                    _json_payload(metadata),
                    recorded_by,
                ),
            )
            feedback_event = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_COLUMNS)
            output_refs = {
                "runtime_notification_email_feedback_event_ids": [str(feedback_event["id"])],
                "runtime_notification_delivery_ids": [delivery_id],
                "runtime_notification_ids": [str(delivery["notification_id"])],
                "runtime_notification_subscription_ids": [str(delivery["subscription_id"])],
                "feedback_type": [feedback_type],
                "recipient_hashes": [recipient_hash] if recipient_hash else [],
                "provider_event_id_hashes": [provider_event_id_hash] if provider_event_id_hash else [],
            }
            audit_event = build_audit_event(
                event_type="runtime_notification_email_feedback_recorded",
                project_id=str(delivery["project_id"]),
                actor_type=actor_type,
                actor_id=recorded_by,
                target_type="runtime_notification_delivery",
                target_id=delivery_id,
                before=delivery,
                after=feedback_event,
                input_refs={
                    "runtime_notification_delivery_ids": [delivery_id],
                    "feedback_type": [feedback_type],
                },
                output_refs=output_refs,
                method_version="runtime_notification_email_feedback_v1",
                reason=reason or f"record runtime notification email {feedback_type} feedback",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            record = self._runtime_notification_email_feedback_from_row(
                cursor=cursor,
                feedback_event=feedback_event,
                delivery=delivery,
            )
        self.connection.commit()
        return record

    def apply_runtime_notification_email_feedback_suppression(
        self,
        suppression: RuntimeNotificationEmailFeedbackSuppressionInput,
    ) -> RuntimeNotificationSubscription:
        feedback_event_id = suppression.feedback_event_id.strip()
        updated_by = suppression.updated_by.strip() or "runtime-console"
        reason = suppression.reason.strip() if suppression.reason else None
        if not feedback_event_id:
            raise ValueError("feedback_event_id is required")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_COLUMNS)}
                FROM runtime_notification_email_feedback_events
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(feedback_event_id),),
            )
            feedback_event = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_COLUMNS)
            if not feedback_event:
                raise ValueError("runtime notification email feedback event not found")
            recipient_hash = _sha256_hex_or_none(
                str(feedback_event.get("recipient_hash") or ""),
                field_name="recipient_hash",
            )
            if not recipient_hash:
                raise ValueError("email feedback event has no recipient_hash to suppress")
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)}
                FROM runtime_notification_subscriptions
                WHERE id = %s
                LIMIT 1
                FOR UPDATE
                """,
                (_uuid(str(feedback_event["subscription_id"])),),
            )
            before = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)
            if not before:
                raise ValueError("runtime notification subscription not found")
            if str(before.get("channel") or "").strip().lower() != "email":
                raise ValueError("email feedback suppression can only be applied to email subscriptions")
            metadata = _json_compatible(before.get("metadata") or {})
            if not isinstance(metadata, dict):
                metadata = {}
            suppression_hashes = list(
                dict.fromkeys([*_metadata_sha256_values(metadata, "email_suppressed_recipient_hashes"), recipient_hash])
            )
            feedback_event_ids = [
                str(value).strip()
                for value in (
                    metadata.get("email_suppression_feedback_event_ids")
                    if isinstance(metadata.get("email_suppression_feedback_event_ids"), (list, tuple, set))
                    else []
                )
                if str(value).strip()
            ]
            metadata["email_suppressed_recipient_hashes"] = suppression_hashes
            metadata["email_suppression_feedback_event_ids"] = list(
                dict.fromkeys([*feedback_event_ids, str(feedback_event["id"])])
            )
            cursor.execute(
                f"""
                UPDATE runtime_notification_subscriptions
                SET metadata = %s,
                    updated_by = %s,
                    updated_at = now()
                WHERE id = %s
                RETURNING {", ".join(RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)}
                """,
                (
                    _json_payload(metadata),
                    updated_by,
                    _uuid(str(before["id"])),
                ),
            )
            after = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)
            audit_event = build_audit_event(
                event_type="runtime_notification_email_feedback_suppression_applied",
                project_id=str(feedback_event["project_id"]),
                actor_type="user",
                actor_id=updated_by,
                target_type="runtime_notification_subscription",
                target_id=str(after["id"]),
                before=before,
                after=after,
                input_refs={
                    "runtime_notification_email_feedback_event_ids": [str(feedback_event["id"])],
                    "runtime_notification_delivery_ids": [str(feedback_event["delivery_id"])],
                    "runtime_notification_ids": [str(feedback_event["notification_id"])],
                    "runtime_notification_subscription_ids": [str(feedback_event["subscription_id"])],
                    "feedback_type": [str(feedback_event["feedback_type"])],
                    "recipient_hashes": [recipient_hash],
                },
                output_refs={
                    "runtime_notification_subscription_ids": [str(after["id"])],
                    "runtime_notification_email_feedback_event_ids": [str(feedback_event["id"])],
                    "email_suppression_hashes": suppression_hashes,
                    "email_suppression_feedback_event_ids": metadata["email_suppression_feedback_event_ids"],
                },
                method_version="runtime_notification_email_feedback_suppression_v1",
                reason=reason or "apply runtime notification email feedback suppression",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            record = self._runtime_notification_subscription_from_row(cursor=cursor, row=after)
        self.connection.commit()
        return record

    def apply_runtime_notification_email_feedback_project_suppression(
        self,
        suppression: RuntimeNotificationEmailFeedbackProjectSuppressionInput,
    ) -> RuntimeNotificationEmailSuppression:
        feedback_event_id = suppression.feedback_event_id.strip()
        updated_by = suppression.updated_by.strip() or "runtime-console"
        reason = suppression.reason.strip() if suppression.reason else None
        if not feedback_event_id:
            raise ValueError("feedback_event_id is required")
        input_metadata = _json_compatible(suppression.metadata or {})
        if not isinstance(input_metadata, dict):
            input_metadata = {}
        if _contains_forbidden_email_feedback_project_suppression_metadata(input_metadata):
            raise ValueError("email feedback project suppression metadata must be hash-only")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_COLUMNS)}
                FROM runtime_notification_email_feedback_events
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(feedback_event_id),),
            )
            feedback_event = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_COLUMNS)
            if not feedback_event:
                raise ValueError("runtime notification email feedback event not found")
            recipient_hash = _sha256_hex_or_none(
                str(feedback_event.get("recipient_hash") or ""),
                field_name="recipient_hash",
            )
            if not recipient_hash:
                raise ValueError("email feedback event has no recipient_hash to suppress")
            project_id = str(feedback_event["project_id"])
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_EMAIL_SUPPRESSION_COLUMNS)}
                FROM runtime_notification_email_suppressions
                WHERE project_id = %s AND recipient_hash = %s
                LIMIT 1
                FOR UPDATE
                """,
                (_uuid(project_id), recipient_hash),
            )
            before = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_EMAIL_SUPPRESSION_COLUMNS)
            existing_metadata = _json_compatible(before.get("metadata") if before else {})
            if not isinstance(existing_metadata, dict):
                existing_metadata = {}
            provider = str(feedback_event.get("provider") or "").strip()
            provider_event_id_hash = _sha256_hex_or_none(
                str(feedback_event.get("provider_event_id_hash") or ""),
                field_name="provider_event_id_hash",
            )
            metadata = {
                **existing_metadata,
                **input_metadata,
                "source": "runtime_notification_email_feedback_project_suppression",
                "feedback_event_id": str(feedback_event["id"]),
                "delivery_id": str(feedback_event["delivery_id"]),
                "notification_id": str(feedback_event["notification_id"]),
                "subscription_id": str(feedback_event["subscription_id"]),
                "feedback_type": str(feedback_event["feedback_type"]),
                "recipient_hash": recipient_hash,
            }
            if provider:
                metadata["provider"] = provider
            if provider_event_id_hash:
                metadata["provider_event_id_hash"] = provider_event_id_hash
            cursor.execute(
                f"""
                INSERT INTO runtime_notification_email_suppressions (
                  project_id, recipient_hash, status, source, source_ref, metadata,
                  created_by, updated_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id, recipient_hash) DO UPDATE SET
                  status = EXCLUDED.status,
                  source = EXCLUDED.source,
                  source_ref = EXCLUDED.source_ref,
                  metadata = EXCLUDED.metadata,
                  updated_by = EXCLUDED.updated_by,
                  updated_at = now()
                RETURNING {RUNTIME_NOTIFICATION_EMAIL_SUPPRESSION_RETURNING}
                """,
                (
                    _uuid(project_id),
                    recipient_hash,
                    "active",
                    "feedback",
                    str(feedback_event["id"]),
                    _json_payload(metadata),
                    updated_by,
                    updated_by,
                ),
            )
            after = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_EMAIL_SUPPRESSION_COLUMNS)
            audit_event = build_audit_event(
                event_type="runtime_notification_email_feedback_project_suppression_applied",
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="runtime_notification_email_suppression",
                target_id=str(after["id"]),
                before=before or None,
                after=after,
                input_refs={
                    "runtime_notification_email_feedback_event_ids": [str(feedback_event["id"])],
                    "runtime_notification_delivery_ids": [str(feedback_event["delivery_id"])],
                    "runtime_notification_ids": [str(feedback_event["notification_id"])],
                    "runtime_notification_subscription_ids": [str(feedback_event["subscription_id"])],
                    "feedback_type": [str(feedback_event["feedback_type"])],
                    "recipient_hashes": [recipient_hash],
                    "provider_event_id_hashes": [provider_event_id_hash] if provider_event_id_hash else [],
                },
                output_refs={
                    "runtime_notification_email_suppression_ids": [str(after["id"])],
                    "runtime_notification_email_feedback_event_ids": [str(feedback_event["id"])],
                    "recipient_hashes": [recipient_hash],
                    "status": [str(after["status"])],
                    "source": [str(after["source"])],
                },
                method_version="runtime_notification_email_feedback_project_suppression_v1",
                reason=reason or "apply runtime notification email feedback project suppression",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        return RuntimeNotificationEmailSuppression(
            suppression=after,
            audit_events=(asdict(audit_event),),
        )

    def list_runtime_notification_email_suppressions(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> RuntimeNotificationEmailSuppressionPage:
        project_id = project_id.strip()
        if not project_id:
            raise ValueError("project_id is required")
        status_filter = (status or "").strip().lower()
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        clauses = ["project_id = %s"]
        params: list[object] = [_uuid(project_id)]
        if status_filter:
            clauses.append("status = %s")
            params.append(status_filter)
        where_clause = "WHERE " + " AND ".join(clauses)
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM runtime_notification_email_suppressions {where_clause}", tuple(params))
            total_count = int(cursor.fetchone()[0])
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_EMAIL_SUPPRESSION_COLUMNS)}
                FROM runtime_notification_email_suppressions
                {where_clause}
                ORDER BY updated_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                tuple([*params, limit, offset]),
            )
            rows = _rows_dict(cursor.fetchall(), RUNTIME_NOTIFICATION_EMAIL_SUPPRESSION_COLUMNS)
            records: list[RuntimeNotificationEmailSuppression] = []
            for row in rows:
                cursor.execute(
                    f"""
                    SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                    FROM audit_events
                    WHERE project_id = %s AND target_type = %s AND target_id = %s
                    ORDER BY created_at DESC
                    LIMIT 5
                    """,
                    (_uuid(project_id), "runtime_notification_email_suppression", str(row["id"])),
                )
                records.append(
                    RuntimeNotificationEmailSuppression(
                        suppression=row,
                        audit_events=_rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS),
                    )
                )
        return RuntimeNotificationEmailSuppressionPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=tuple(records),
        )

    def export_runtime_notification_email_suppressions_csv(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        page = self.list_runtime_notification_email_suppressions(
            project_id=project_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_notification_email_suppressions_csv(page)
        filters = {
            "project_id": project_id.strip(),
            "status": status.strip().lower() if status else None,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_notification_email_suppressions_csv",
            filename="runtime-notification-email-suppressions.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=page.total_count,
            row_count=len(page.records),
        )

    def save_runtime_notification_email_suppression(
        self,
        suppression: RuntimeNotificationEmailSuppressionInput,
    ) -> RuntimeNotificationEmailSuppression:
        project_id = suppression.project_id.strip()
        recipient_hash = _sha256_hex_or_none(suppression.recipient_hash, field_name="recipient_hash")
        status = suppression.status.strip().lower()
        source = suppression.source.strip().lower() or "manual"
        source_ref = suppression.source_ref.strip() if suppression.source_ref else None
        updated_by = suppression.updated_by.strip() or "runtime-console"
        reason = suppression.reason.strip() if suppression.reason else None
        if not project_id:
            raise ValueError("project_id is required")
        if not recipient_hash:
            raise ValueError("recipient_hash is required")
        if status not in {"active", "inactive"}:
            raise ValueError("status must be active or inactive")
        metadata = _json_compatible(suppression.metadata or {})
        if not isinstance(metadata, dict):
            metadata = {}
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_EMAIL_SUPPRESSION_COLUMNS)}
                FROM runtime_notification_email_suppressions
                WHERE project_id = %s AND recipient_hash = %s
                LIMIT 1
                FOR UPDATE
                """,
                (_uuid(project_id), recipient_hash),
            )
            before = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_EMAIL_SUPPRESSION_COLUMNS)
            cursor.execute(
                f"""
                INSERT INTO runtime_notification_email_suppressions (
                  project_id, recipient_hash, status, source, source_ref, metadata,
                  created_by, updated_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id, recipient_hash) DO UPDATE SET
                  status = EXCLUDED.status,
                  source = EXCLUDED.source,
                  source_ref = EXCLUDED.source_ref,
                  metadata = EXCLUDED.metadata,
                  updated_by = EXCLUDED.updated_by,
                  updated_at = now()
                RETURNING {RUNTIME_NOTIFICATION_EMAIL_SUPPRESSION_RETURNING}
                """,
                (
                    _uuid(project_id),
                    recipient_hash,
                    status,
                    source,
                    source_ref,
                    _json_payload(metadata),
                    updated_by,
                    updated_by,
                ),
            )
            after = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_EMAIL_SUPPRESSION_COLUMNS)
            audit_event = build_audit_event(
                event_type="runtime_notification_email_suppression_saved",
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="runtime_notification_email_suppression",
                target_id=str(after["id"]),
                before=before or None,
                after=after,
                input_refs={
                    "recipient_hashes": [recipient_hash],
                    "status": [status],
                    "source": [source],
                    "source_ref": [source_ref] if source_ref else [],
                },
                output_refs={
                    "runtime_notification_email_suppression_ids": [str(after["id"])],
                    "recipient_hashes": [recipient_hash],
                    "status": [str(after["status"])],
                    "source": [str(after["source"])],
                },
                method_version="runtime_notification_email_suppression_v1",
                reason=reason or "save runtime notification email suppression",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        return RuntimeNotificationEmailSuppression(
            suppression=after,
            audit_events=(asdict(audit_event),),
        )

    def _load_runtime_notification_email_preference_subscription(
        self,
        *,
        cursor: DbCursor,
        project_id: str,
        delivery_id: str,
        notification_id: str,
        subscription_id: str,
        for_update: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        cursor.execute(
            f"""
            SELECT {", ".join(RUNTIME_NOTIFICATION_DELIVERY_COLUMNS)}
            FROM runtime_notification_deliveries
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(delivery_id),),
        )
        delivery = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_DELIVERY_COLUMNS)
        if not delivery:
            raise ValueError("runtime notification delivery not found")
        if str(delivery.get("project_id")) != project_id:
            raise ValueError("runtime notification delivery project mismatch")
        if str(delivery.get("notification_id")) != notification_id:
            raise ValueError("runtime notification delivery notification mismatch")
        if str(delivery.get("subscription_id")) != subscription_id:
            raise ValueError("runtime notification delivery subscription mismatch")
        if str(delivery.get("channel") or "").strip().lower() != "email":
            raise ValueError("email preference can only apply to email deliveries")
        cursor.execute(
            f"""
            SELECT {", ".join(RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)}
            FROM runtime_notification_subscriptions
            WHERE id = %s
            LIMIT 1
            {"FOR UPDATE" if for_update else ""}
            """,
            (_uuid(subscription_id),),
        )
        subscription = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)
        if not subscription:
            raise ValueError("runtime notification subscription not found")
        if str(subscription.get("project_id")) != project_id:
            raise ValueError("runtime notification subscription project mismatch")
        if str(subscription.get("channel") or "").strip().lower() != "email":
            raise ValueError("email preference can only apply to email subscriptions")
        return delivery, subscription

    def apply_runtime_notification_email_preference_unsubscribe(
        self,
        unsubscribe: RuntimeNotificationEmailPreferenceUnsubscribeInput,
    ) -> RuntimeNotificationSubscription:
        project_id = unsubscribe.project_id.strip()
        delivery_id = unsubscribe.delivery_id.strip()
        notification_id = unsubscribe.notification_id.strip()
        subscription_id = unsubscribe.subscription_id.strip()
        recipient_hash = _sha256_hex_or_none(unsubscribe.recipient_hash, field_name="recipient_hash")
        token_hash = _sha256_hex_or_none(unsubscribe.token_hash, field_name="token_hash")
        updated_by = unsubscribe.updated_by.strip() or "email-preference-token"
        reason = unsubscribe.reason.strip() if unsubscribe.reason else None
        if not project_id:
            raise ValueError("project_id is required")
        if not delivery_id:
            raise ValueError("delivery_id is required")
        if not notification_id:
            raise ValueError("notification_id is required")
        if not subscription_id:
            raise ValueError("subscription_id is required")
        if not recipient_hash:
            raise ValueError("recipient_hash is required")
        if not token_hash:
            raise ValueError("token_hash is required")
        with self.connection.cursor() as cursor:
            _, before = self._load_runtime_notification_email_preference_subscription(
                cursor=cursor,
                project_id=project_id,
                delivery_id=delivery_id,
                notification_id=notification_id,
                subscription_id=subscription_id,
                for_update=True,
            )
            metadata = _json_compatible(before.get("metadata") or {})
            if not isinstance(metadata, dict):
                metadata = {}
            suppression_hashes = list(
                dict.fromkeys([*_metadata_sha256_values(metadata, "email_suppressed_recipient_hashes"), recipient_hash])
            )
            token_hashes = list(
                dict.fromkeys([*_metadata_sha256_values(metadata, "email_unsubscribe_token_hashes"), token_hash])
            )
            metadata["email_suppressed_recipient_hashes"] = suppression_hashes
            metadata["email_unsubscribe_token_hashes"] = token_hashes
            metadata["email_unsubscribe_source"] = "runtime_notification_email_preference_token"
            cursor.execute(
                f"""
                UPDATE runtime_notification_subscriptions
                SET metadata = %s,
                    updated_by = %s,
                    updated_at = now()
                WHERE id = %s
                RETURNING {", ".join(RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)}
                """,
                (_json_payload(metadata), updated_by, _uuid(subscription_id)),
            )
            after = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)
            audit_event = build_audit_event(
                event_type="runtime_notification_email_preference_unsubscribed",
                project_id=project_id,
                actor_type="system" if updated_by == "email-preference-token" else "user",
                actor_id=updated_by,
                target_type="runtime_notification_subscription",
                target_id=subscription_id,
                before=before,
                after=after,
                input_refs={
                    "runtime_notification_delivery_ids": [delivery_id],
                    "runtime_notification_ids": [notification_id],
                    "runtime_notification_subscription_ids": [subscription_id],
                    "recipient_hashes": [recipient_hash],
                    "email_preference_token_hashes": [token_hash],
                    "action": [RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_UNSUBSCRIBE_ACTION],
                },
                output_refs={
                    "runtime_notification_subscription_ids": [subscription_id],
                    "email_suppression_hashes": suppression_hashes,
                    "email_unsubscribe_token_hashes": token_hashes,
                },
                method_version="runtime_notification_email_preference_unsubscribe_v1",
                reason=reason or "apply runtime notification email preference unsubscribe token",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            record = self._runtime_notification_subscription_from_row(cursor=cursor, row=after)
        self.connection.commit()
        return record

    def get_runtime_notification_email_preference_status(
        self,
        *,
        project_id: str,
        delivery_id: str,
        notification_id: str,
        subscription_id: str,
        recipient_hash: str,
        token_hash: str,
    ) -> RuntimeNotificationEmailPreferenceStatus:
        project_id = project_id.strip()
        delivery_id = delivery_id.strip()
        notification_id = notification_id.strip()
        subscription_id = subscription_id.strip()
        recipient_hash = _sha256_hex_or_none(recipient_hash, field_name="recipient_hash")
        token_hash = _sha256_hex_or_none(token_hash, field_name="token_hash")
        if not project_id:
            raise ValueError("project_id is required")
        if not delivery_id:
            raise ValueError("delivery_id is required")
        if not notification_id:
            raise ValueError("notification_id is required")
        if not subscription_id:
            raise ValueError("subscription_id is required")
        if not recipient_hash:
            raise ValueError("recipient_hash is required")
        if not token_hash:
            raise ValueError("token_hash is required")
        with self.connection.cursor() as cursor:
            delivery, subscription = self._load_runtime_notification_email_preference_subscription(
                cursor=cursor,
                project_id=project_id,
                delivery_id=delivery_id,
                notification_id=notification_id,
                subscription_id=subscription_id,
                for_update=False,
            )
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_COLUMNS)}
                FROM runtime_notifications
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(notification_id),),
            )
            notification_row = cursor.fetchone()
            notification = _row_dict(notification_row, RUNTIME_NOTIFICATION_COLUMNS) if notification_row else None
            metadata = _json_compatible(subscription.get("metadata") or {})
            if not isinstance(metadata, dict):
                metadata = {}
            suppression_hashes = _metadata_sha256_values(metadata, "email_suppressed_recipient_hashes")
            unsubscribe_token_hashes = _metadata_sha256_values(metadata, "email_unsubscribe_token_hashes")
            resubscribe_token_hashes = _metadata_sha256_values(metadata, "email_resubscribe_token_hashes")
            suppressed = recipient_hash in suppression_hashes
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE project_id = %s AND target_type = %s AND target_id = %s
                ORDER BY created_at DESC
                LIMIT 5
                """,
                (_uuid(project_id), "runtime_notification_subscription", subscription_id),
            )
            audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeNotificationEmailPreferenceStatus(
            preference={
                "project_id": project_id,
                "delivery_id": delivery_id,
                "notification_id": notification_id,
                "subscription_id": subscription_id,
                "recipient_hash": recipient_hash,
                "channel": "email",
                "status": "unsubscribed" if suppressed else "subscribed",
                "suppressed": suppressed,
                "subscription_status": str(subscription.get("status") or ""),
                "event_types": subscription.get("event_types") or [],
                "severity_threshold": subscription.get("severity_threshold"),
                "email_suppressed_recipient_hash_count": len(suppression_hashes),
                "email_unsubscribe_token_hash_seen": token_hash in unsubscribe_token_hashes,
                "email_resubscribe_token_hash_seen": token_hash in resubscribe_token_hashes,
                "email_unsubscribe_source": metadata.get("email_unsubscribe_source"),
                "email_resubscribe_source": metadata.get("email_resubscribe_source"),
                "email_preference_token_hash": token_hash,
                "method_version": "runtime_notification_email_preference_status_v1",
            },
            delivery={
                "id": str(delivery.get("id")),
                "project_id": str(delivery.get("project_id")),
                "notification_id": str(delivery.get("notification_id")),
                "subscription_id": str(delivery.get("subscription_id")),
                "channel": str(delivery.get("channel") or ""),
                "status": str(delivery.get("status") or ""),
                "attempt_count": int(delivery.get("attempt_count") or 0),
                "response_status": delivery.get("response_status"),
                "response_body_hash": delivery.get("response_body_hash"),
                "created_at": delivery.get("created_at"),
                "updated_by": delivery.get("updated_by"),
                "updated_at": delivery.get("updated_at"),
            },
            notification={
                "id": str(notification.get("id")),
                "project_id": str(notification.get("project_id")),
                "notification_type": str(notification.get("notification_type") or ""),
                "severity": str(notification.get("severity") or ""),
                "title": notification.get("title"),
                "message": notification.get("message"),
                "target_type": notification.get("target_type"),
                "target_id": notification.get("target_id"),
                "status": notification.get("status"),
                "created_at": notification.get("created_at"),
            }
            if notification
            else None,
            subscription={
                "id": str(subscription.get("id")),
                "project_id": str(subscription.get("project_id")),
                "channel": str(subscription.get("channel") or ""),
                "event_types": subscription.get("event_types") or [],
                "severity_threshold": subscription.get("severity_threshold"),
                "status": subscription.get("status"),
                "metadata": {
                    "email_suppressed_recipient_hash_count": len(suppression_hashes),
                    "email_unsubscribe_token_hash_count": len(unsubscribe_token_hashes),
                    "email_resubscribe_token_hash_count": len(resubscribe_token_hashes),
                    "email_unsubscribe_source": metadata.get("email_unsubscribe_source"),
                    "email_resubscribe_source": metadata.get("email_resubscribe_source"),
                },
                "created_by": subscription.get("created_by"),
                "created_at": subscription.get("created_at"),
                "updated_by": subscription.get("updated_by"),
                "updated_at": subscription.get("updated_at"),
            },
            audit_events=audit_events,
        )

    def apply_runtime_notification_email_preference_resubscribe(
        self,
        resubscribe: RuntimeNotificationEmailPreferenceResubscribeInput,
    ) -> RuntimeNotificationSubscription:
        project_id = resubscribe.project_id.strip()
        delivery_id = resubscribe.delivery_id.strip()
        notification_id = resubscribe.notification_id.strip()
        subscription_id = resubscribe.subscription_id.strip()
        recipient_hash = _sha256_hex_or_none(resubscribe.recipient_hash, field_name="recipient_hash")
        token_hash = _sha256_hex_or_none(resubscribe.token_hash, field_name="token_hash")
        updated_by = resubscribe.updated_by.strip() or "email-preference-token"
        reason = resubscribe.reason.strip() if resubscribe.reason else None
        if not project_id:
            raise ValueError("project_id is required")
        if not delivery_id:
            raise ValueError("delivery_id is required")
        if not notification_id:
            raise ValueError("notification_id is required")
        if not subscription_id:
            raise ValueError("subscription_id is required")
        if not recipient_hash:
            raise ValueError("recipient_hash is required")
        if not token_hash:
            raise ValueError("token_hash is required")
        with self.connection.cursor() as cursor:
            _, before = self._load_runtime_notification_email_preference_subscription(
                cursor=cursor,
                project_id=project_id,
                delivery_id=delivery_id,
                notification_id=notification_id,
                subscription_id=subscription_id,
                for_update=True,
            )
            metadata = _json_compatible(before.get("metadata") or {})
            if not isinstance(metadata, dict):
                metadata = {}
            suppression_hashes_before = list(_metadata_sha256_values(metadata, "email_suppressed_recipient_hashes"))
            suppression_hashes = [value for value in suppression_hashes_before if value != recipient_hash]
            token_hashes = list(
                dict.fromkeys([*_metadata_sha256_values(metadata, "email_resubscribe_token_hashes"), token_hash])
            )
            metadata["email_suppressed_recipient_hashes"] = suppression_hashes
            metadata["email_resubscribe_token_hashes"] = token_hashes
            metadata["email_resubscribe_source"] = "runtime_notification_email_preference_token"
            cursor.execute(
                f"""
                UPDATE runtime_notification_subscriptions
                SET metadata = %s,
                    updated_by = %s,
                    updated_at = now()
                WHERE id = %s
                RETURNING {", ".join(RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)}
                """,
                (_json_payload(metadata), updated_by, _uuid(subscription_id)),
            )
            after = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)
            audit_event = build_audit_event(
                event_type="runtime_notification_email_preference_resubscribed",
                project_id=project_id,
                actor_type="system" if updated_by == "email-preference-token" else "user",
                actor_id=updated_by,
                target_type="runtime_notification_subscription",
                target_id=subscription_id,
                before=before,
                after=after,
                input_refs={
                    "runtime_notification_delivery_ids": [delivery_id],
                    "runtime_notification_ids": [notification_id],
                    "runtime_notification_subscription_ids": [subscription_id],
                    "recipient_hashes": [recipient_hash],
                    "email_preference_token_hashes": [token_hash],
                    "action": [RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_RESUBSCRIBE_ACTION],
                },
                output_refs={
                    "runtime_notification_subscription_ids": [subscription_id],
                    "email_suppression_hashes": suppression_hashes,
                    "email_removed_suppression_hashes": [recipient_hash]
                    if recipient_hash in suppression_hashes_before
                    else [],
                    "email_resubscribe_token_hashes": token_hashes,
                },
                method_version="runtime_notification_email_preference_resubscribe_v1",
                reason=reason or "apply runtime notification email preference resubscribe token",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            record = self._runtime_notification_subscription_from_row(cursor=cursor, row=after)
        self.connection.commit()
        return record

    def claim_next_runtime_report_export_job(
        self,
        *,
        updated_by: str = "runtime-worker",
        lease_seconds: int = 900,
    ) -> RuntimeReportExportJob | None:
        updated_by = updated_by.strip()
        if not updated_by:
            raise ValueError("updated_by is required")
        lease_seconds = max(1, int(lease_seconds))
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(REPORT_EXPORT_JOB_COLUMNS)}
                FROM report_export_jobs
                WHERE (
                  (status = %s AND (next_attempt_at IS NULL OR next_attempt_at <= now()))
                  OR (status = %s AND lease_expires_at IS NOT NULL AND lease_expires_at <= now())
                )
                  AND attempt_count < max_attempts
                ORDER BY
                  CASE WHEN status = %s THEN 0 ELSE 1 END,
                  COALESCE(next_attempt_at, requested_at) ASC,
                  requested_at ASC,
                  id ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                ("queued", "running", "queued"),
            )
            before = _row_dict(cursor.fetchone(), REPORT_EXPORT_JOB_COLUMNS)
            if not before:
                return None
            now = datetime.now(UTC)
            lease_expires_at = now + timedelta(seconds=lease_seconds)
            cursor.execute(
                f"""
                UPDATE report_export_jobs
                SET status = %s,
                    started_at = COALESCE(started_at, %s),
                    attempt_count = attempt_count + 1,
                    lease_expires_at = %s,
                    next_attempt_at = NULL,
                    updated_by = %s,
                    updated_at = %s
                WHERE id = %s AND status = %s
                RETURNING {REPORT_EXPORT_JOB_RETURNING}
                """,
                ("running", now, lease_expires_at, updated_by, now, _uuid(str(before["id"])), str(before["status"])),
            )
            after = _row_dict(cursor.fetchone(), REPORT_EXPORT_JOB_COLUMNS)
            if not after:
                self.connection.rollback()
                return None
            job_id = str(after["id"])
            audit_event = build_audit_event(
                event_type="report_export_job_status_updated",
                project_id=str(after["project_id"]),
                actor_type="worker",
                actor_id=updated_by,
                target_type="report_export_job",
                target_id=job_id,
                before=before,
                after=after,
                input_refs={
                    "report_export_job_ids": [job_id],
                    "status": ["running"],
                },
                output_refs={
                    "report_export_job_ids": [job_id],
                    "claimed": [True],
                },
                method_version="runtime_report_export_job_claim_v1",
                reason="claim queued report export job",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            record = self._runtime_report_export_job_from_row(cursor=cursor, row=after)
        self.connection.commit()
        return record

    def update_runtime_report_export_job_status(
        self,
        update: RuntimeReportExportJobStatusInput,
    ) -> RuntimeReportExportJob:
        job_id = update.job_id.strip()
        status = update.status.strip().lower()
        updated_by = update.updated_by.strip()
        report_export_id = update.report_export_id.strip() if update.report_export_id else None
        artifact_url = update.artifact_url.strip() if update.artifact_url else None
        error_message = update.error_message.strip() if update.error_message else None
        next_attempt_at = update.next_attempt_at
        lease_expires_at = update.lease_expires_at
        reason = update.reason.strip() if update.reason else None
        allowed_statuses = {"queued", "running", "succeeded", "failed", "cancelled", "dead_letter"}
        if not job_id:
            raise ValueError("job_id is required")
        if status not in allowed_statuses:
            raise ValueError("status must be queued, running, succeeded, failed, cancelled, or dead_letter")
        if not updated_by:
            raise ValueError("updated_by is required")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(REPORT_EXPORT_JOB_COLUMNS)}
                FROM report_export_jobs
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(job_id),),
            )
            before = _row_dict(cursor.fetchone(), REPORT_EXPORT_JOB_COLUMNS)
            if not before:
                raise ValueError("report_export_job not found")
            if report_export_id:
                report_export = self._load_report_export_by_id(
                    cursor=cursor,
                    report_export_id=report_export_id,
                )
                if not report_export:
                    raise ValueError("report_export not found")
                if str(report_export["project_id"]) != str(before["project_id"]):
                    raise ValueError("report_export does not belong to project")
            now = datetime.now(UTC)
            cursor.execute(
                f"""
                UPDATE report_export_jobs
                SET status = %s,
                    report_export_id = COALESCE(%s, report_export_id),
                    started_at = CASE WHEN %s = 'running' AND started_at IS NULL THEN %s ELSE started_at END,
                    completed_at = CASE WHEN %s IN ('succeeded', 'failed', 'cancelled', 'dead_letter') THEN %s ELSE completed_at END,
                    lease_expires_at = CASE WHEN %s = 'running' THEN COALESCE(%s, lease_expires_at) ELSE NULL END,
                    next_attempt_at = %s,
                    artifact_url = COALESCE(%s, artifact_url),
                    error_message = %s,
                    updated_by = %s,
                    updated_at = %s
                WHERE id = %s
                RETURNING {REPORT_EXPORT_JOB_RETURNING}
                """,
                (
                    status,
                    _uuid(report_export_id),
                    status,
                    now,
                    status,
                    now,
                    status,
                    lease_expires_at,
                    next_attempt_at,
                    artifact_url,
                    error_message,
                    updated_by,
                    now,
                    _uuid(job_id),
                ),
            )
            after = _row_dict(cursor.fetchone(), REPORT_EXPORT_JOB_COLUMNS)
            audit_event = build_audit_event(
                event_type="report_export_job_status_updated",
                project_id=str(after["project_id"]),
                actor_type="worker" if updated_by == "runtime-worker" else "user",
                actor_id=updated_by,
                target_type="report_export_job",
                target_id=job_id,
                before=before,
                after=after,
                input_refs={
                    "report_export_job_ids": [job_id],
                    "report_export_ids": [report_export_id] if report_export_id else [],
                    "status": [status],
                    "next_attempt_at": [next_attempt_at.isoformat()] if next_attempt_at else [],
                },
                output_refs={
                    "report_export_job_ids": [job_id],
                    "artifact_url": [artifact_url] if artifact_url else [],
                },
                method_version="runtime_report_export_job_status_v1",
                reason=reason or f"mark report export job {status}",
            )
            notification_audit_events: tuple[AuditEvent, ...] = ()
            if status in {"succeeded", "failed", "cancelled", "dead_letter"}:
                _, notification_audit_events = self._insert_report_export_job_notification(
                    cursor=cursor,
                    job=after,
                    updated_by=updated_by,
                    reason=reason or f"report export job {status}",
                )
            audit_events = (audit_event, *notification_audit_events)
            self.save_audit_events(audit_events, cursor=cursor)
            record = self._runtime_report_export_job_from_row(cursor=cursor, row=after)
        self.connection.commit()
        return record

    def record_runtime_report_management_event(
        self,
        event: RuntimeReportManagementInput,
    ) -> RuntimeReportExport:
        report_export_id = event.report_export_id.strip()
        status = _normalize_report_management_status(event.status)
        updated_by = event.updated_by.strip()
        note = event.note.strip() if event.note else None
        allowed_statuses = {"internal_review", "client_ready", "archived"}
        if not report_export_id:
            raise ValueError("report_export_id is required")
        if status not in allowed_statuses:
            raise ValueError("status must be internal_review, client_ready, or archived")
        if not updated_by:
            raise ValueError("updated_by is required")
        with self.connection.cursor() as cursor:
            report_export = self._load_report_export_by_id(
                cursor=cursor,
                report_export_id=report_export_id,
            )
            if not report_export:
                raise ValueError("report_export not found")
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE target_type = %s AND target_id = %s
                  AND event_type = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                ("report_export", report_export_id, "report_export_management_recorded"),
            )
            previous_management_event = _row_dict(cursor.fetchone(), AUDIT_EVENT_COLUMNS)
            before = previous_management_event or None
            after = {
                "report_export_id": report_export_id,
                "status": status,
                "note": note,
                "updated_by": updated_by,
                "report_version": report_export.get("report_version"),
                "methodology_hash": report_export.get("methodology_hash"),
            }
            audit_event = build_audit_event(
                event_type="report_export_management_recorded",
                project_id=str(report_export["project_id"]),
                actor_type="user",
                actor_id=updated_by,
                target_type="report_export",
                target_id=report_export_id,
                before=before,
                after=after,
                input_refs={
                    "report_export_ids": [report_export_id],
                    "status": [status],
                },
                output_refs={"audit_event_ids": []},
                method_version="report_export_management_v1",
                reason=note or f"mark report export {status}",
            )
            audit_event = AuditEvent(
                id=audit_event.id,
                event_type=audit_event.event_type,
                project_id=audit_event.project_id,
                actor_type=audit_event.actor_type,
                actor_id=audit_event.actor_id,
                target_type=audit_event.target_type,
                target_id=audit_event.target_id,
                before_hash=audit_event.before_hash,
                after_hash=audit_event.after_hash,
                input_refs=audit_event.input_refs,
                output_refs={"audit_event_ids": [audit_event.id]},
                method_version=audit_event.method_version,
                reason=audit_event.reason,
                created_at=audit_event.created_at,
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            record = self._load_runtime_report_export(
                cursor=cursor,
                report_export=report_export,
            )
        self.connection.commit()
        return record

    def get_runtime_traceability_detail(
        self,
        *,
        project_id: str | None = None,
        report_export_id: str | None = None,
    ) -> RuntimeTraceabilityDetail | None:
        filters: list[str] = []
        params: list[object] = []
        if report_export_id:
            filters.append("subject_type = %s")
            params.append("report_export")
            filters.append("subject_id = %s")
            params.append(_uuid(report_export_id))
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(TRACEABILITY_BUNDLE_COLUMNS)}
                FROM traceability_bundles
                {where_clause}
                ORDER BY id DESC
                LIMIT 1
                """,
                tuple(params),
            )
            bundle_row = cursor.fetchone()
            if not bundle_row:
                return None
            bundle = _row_dict(bundle_row, TRACEABILITY_BUNDLE_COLUMNS)

            report_exports = tuple(
                self._load_report_export_by_id(cursor=cursor, report_export_id=str(value))
                for value in bundle["report_export_ids"]
            )
            report_exports = tuple(report for report in report_exports if report)
            score_snapshots = tuple(
                runtime_snapshot
                for score_snapshot_id in tuple(str(value) for value in bundle["score_snapshot_ids"])
                if (
                    runtime_snapshot := self._load_score_snapshot_by_id(
                        cursor=cursor,
                        score_snapshot_id=score_snapshot_id,
                    )
                )
                is not None
            )
            evidence_runs = tuple(
                runtime_evidence
                for answer_run_id in tuple(str(value) for value in bundle["answer_run_ids"])
                if (
                    runtime_evidence := self._load_evidence_run_by_id(
                        cursor=cursor,
                        answer_run_id=answer_run_id,
                    )
                )
                is not None
            )
            cursor.execute("SELECT count(*) FROM source_graphs WHERE project_id = %s", (_uuid(str(bundle["project_id"])),))
            graph_count_row = cursor.fetchone()
            graph_count = int(graph_count_row[0] if not isinstance(graph_count_row, dict) else graph_count_row["count"])
            citation_graph = (
                self._load_runtime_citation_graph(cursor=cursor, project_id=str(bundle["project_id"]))
                if graph_count > 0
                else None
            )
            action_recommendations = tuple(
                action
                for action_id in tuple(str(value) for value in bundle["action_recommendation_ids"])
                if (action := self._load_action_recommendation_by_id(cursor=cursor, action_id=action_id)) is not None
            )
            content_drafts = tuple(
                draft
                for content_draft_id in tuple(str(value) for value in bundle["content_draft_ids"])
                if (
                    draft := self._load_runtime_content_draft_by_id(
                        cursor=cursor,
                        content_draft_id=content_draft_id,
                    )
                )
                is not None
            )
            audit_events = tuple(
                event
                for audit_event_id in tuple(str(value) for value in bundle["audit_event_ids"])
                if (event := self._load_audit_event_by_id(cursor=cursor, audit_event_id=audit_event_id)) is not None
            )
            cursor.execute(
                f"""
                SELECT {", ".join(EVIDENCE_LINK_COLUMNS)}
                FROM evidence_links
                WHERE project_id = %s AND (
                    source_id = ANY(%s::uuid[]) OR target_id = ANY(%s::uuid[])
                )
                ORDER BY relation_type ASC, id ASC
                """,
                (
                    _uuid(str(bundle["project_id"])),
                    _uuid_array(
                        (
                            str(bundle["subject_id"]),
                            *tuple(str(value) for value in bundle["report_export_ids"]),
                        )
                    ),
                    _uuid_array(
                        (
                            *tuple(str(value) for value in bundle["score_snapshot_ids"]),
                            *tuple(str(value) for value in bundle["score_contribution_ids"]),
                            *tuple(str(value) for value in bundle["source_graph_ids"]),
                            *tuple(str(value) for value in bundle["action_recommendation_ids"]),
                            *tuple(str(value) for value in bundle["content_draft_ids"]),
                        )
                    ),
                ),
            )
            evidence_links = _rows_dict(cursor.fetchall(), EVIDENCE_LINK_COLUMNS)
        return RuntimeTraceabilityDetail(
            traceability_bundle=bundle,
            report_exports=report_exports,
            score_snapshots=score_snapshots,
            evidence_runs=evidence_runs,
            citation_graph=citation_graph,
            action_recommendations=action_recommendations,
            content_drafts=content_drafts,
            audit_events=audit_events,
            evidence_links=evidence_links,
        )

    def export_runtime_traceability_csv(
        self,
        *,
        project_id: str | None = None,
        report_export_id: str | None = None,
    ) -> RuntimeEvidenceExport:
        normalized_project_id = project_id.strip() if project_id else None
        normalized_report_export_id = report_export_id.strip() if report_export_id else None
        detail = self.get_runtime_traceability_detail(
            project_id=normalized_project_id,
            report_export_id=normalized_report_export_id,
        )
        if detail is None:
            raise ValueError("Runtime traceability bundle not found")
        content = _render_runtime_traceability_csv(detail)
        bundle = detail.traceability_bundle
        filters = {
            "project_id": normalized_project_id or str(bundle.get("project_id") or ""),
            "report_export_id": normalized_report_export_id,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_traceability_csv",
            filename="runtime-traceability.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=1,
            row_count=max(1, len(detail.evidence_links)),
        )

    def _load_report_export_by_id(
        self,
        *,
        cursor: DbCursor,
        report_export_id: str,
    ) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT {", ".join(REPORT_EXPORT_COLUMNS)}
            FROM report_exports
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(report_export_id),),
        )
        report_row = cursor.fetchone()
        return _row_dict(report_row, REPORT_EXPORT_COLUMNS) if report_row else None

    def _runtime_report_export_job_from_row(
        self,
        *,
        cursor: DbCursor,
        row: dict[str, Any],
    ) -> RuntimeReportExportJob:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (_uuid(str(row["project_id"])), "report_export_job", str(row["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeReportExportJob(
            report_export_job=row,
            audit_events=audit_events,
        )

    def _insert_report_export_job_notification(
        self,
        *,
        cursor: DbCursor,
        job: dict[str, Any],
        updated_by: str,
        reason: str,
    ) -> tuple[dict[str, Any], tuple[AuditEvent, ...]]:
        status = str(job["status"])
        job_id = str(job["id"])
        project_id = str(job["project_id"])
        severity_by_status = {
            "succeeded": "info",
            "failed": "warning",
            "dead_letter": "critical",
            "cancelled": "warning",
        }
        title_by_status = {
            "succeeded": "Report export succeeded",
            "failed": "Report export failed",
            "dead_letter": "Report export dead-lettered",
            "cancelled": "Report export cancelled",
        }
        notification_id = _stable_id("runtime-notification", "report-export-job", job_id, status, job.get("updated_at"))
        title = title_by_status.get(status, "Report export job updated")
        artifact_type = str(job.get("artifact_type") or "artifact")
        template = str(job.get("template") or "standard")
        message = f"{artifact_type}/{template} report export job {status}."
        if job.get("artifact_url"):
            message = f"{message} Artifact is ready."
        if job.get("error_message"):
            message = f"{message} Error: {job['error_message']}"
        payload = {
            "report_export_job_id": job_id,
            "report_export_id": job.get("report_export_id"),
            "status": status,
            "artifact_type": artifact_type,
            "template": template,
            "artifact_url": job.get("artifact_url"),
            "error_message": job.get("error_message"),
            "attempt_count": job.get("attempt_count"),
            "max_attempts": job.get("max_attempts"),
        }
        return self._insert_runtime_notification(
            cursor=cursor,
            notification_id=notification_id,
            project_id=project_id,
            notification_type="report_export_job",
            severity=severity_by_status.get(status, "info"),
            title=title,
            message=message,
            target_type="report_export_job",
            target_id=job_id,
            payload=payload,
            created_by=updated_by,
            reason=reason,
            input_refs={
                "report_export_job_ids": [job_id],
                "status": [status],
            },
        )

    def _insert_runtime_alert_notification(
        self,
        *,
        cursor: DbCursor,
        alert: dict[str, Any],
        evidence_refs: tuple[dict[str, Any], ...],
        related_actions: tuple[dict[str, Any], ...],
        latest_management_status: str | None,
        created_by: str,
        reason: str,
    ) -> tuple[dict[str, Any], tuple[AuditEvent, ...]]:
        alert_id = str(alert.get("id") or "").strip()
        project_id = str(alert.get("project_id") or "").strip()
        alert_type = str(alert.get("alert_type") or "runtime_alert").strip().lower()
        severity = str(alert.get("severity") or "warning").strip().lower()
        severity = "critical" if severity == "critical" else "warning"
        source = str(alert.get("source") or "runtime_alert").strip()
        source_id = str(alert.get("source_id") or alert_id).strip()
        title = f"Runtime alert: {alert.get('title') or alert_type}"
        metric_name = str(alert.get("metric_name") or "metric")
        metric_value = alert.get("metric_value")
        threshold = alert.get("threshold")
        message = f"{alert_type} alert from {source}."
        if metric_value is not None:
            message = f"{message} {metric_name}={metric_value}."
        if threshold is not None:
            message = f"{message} threshold={threshold}."
        payload = {
            "alert_id": alert_id,
            "alert_type": alert_type,
            "severity": severity,
            "title": alert.get("title"),
            "summary": alert.get("summary"),
            "metric_name": alert.get("metric_name"),
            "metric_value": metric_value,
            "threshold": threshold,
            "source": source,
            "source_id": source_id,
            "rule_version": alert.get("rule_version"),
            "latest_management_status": latest_management_status,
            "evidence_refs": tuple(evidence_refs),
            "related_action_ids": [str(action.get("id")) for action in related_actions if action.get("id")],
        }
        notification_id = _stable_id("runtime-notification", "runtime-alert", project_id, alert_id, source_id)
        return self._insert_runtime_notification(
            cursor=cursor,
            notification_id=notification_id,
            project_id=project_id,
            notification_type="runtime_alert",
            severity=severity,
            title=title,
            message=message,
            target_type="runtime_alert",
            target_id=alert_id,
            payload=payload,
            created_by=created_by,
            reason=reason,
            input_refs={
                "runtime_alert_ids": [alert_id],
                "alert_type": [alert_type],
                "source": [source],
                "source_id": [source_id],
            },
        )

    def _insert_entity_alias_assignment_overdue_notification(
        self,
        *,
        cursor: DbCursor,
        review: dict[str, Any],
        created_by: str,
        reason: str,
    ) -> tuple[dict[str, Any], tuple[AuditEvent, ...]]:
        review_id = str(review.get("id") or "").strip()
        project_id = str(review.get("project_id") or "").strip()
        candidate_id = str(review.get("candidate_id") or "").strip()
        alias = str(review.get("alias") or "alias candidate").strip()
        assignee = str(review.get("assigned_to") or "unassigned").strip()
        priority = str(review.get("priority") or "normal").strip().lower()
        assignment_status = str(review.get("assignment_status") or "assigned").strip().lower()
        severity = "critical" if priority == "urgent" else "warning"
        due_at = _coerce_datetime(review.get("due_at"))
        due_text = due_at.isoformat() if due_at else str(review.get("due_at") or "")
        title = f"Alias assignment overdue: {alias}"
        message = f"{alias} alias candidate review is overdue for {assignee}."
        if due_text:
            message = f"{message} due_at={due_text}."
        payload = {
            "entity_alias_candidate_review_id": review_id,
            "candidate_id": candidate_id,
            "entity_id": review.get("entity_id"),
            "entity_kind": review.get("entity_kind"),
            "alias": alias,
            "alias_type": review.get("alias_type"),
            "decision": review.get("decision"),
            "assigned_to": assignee,
            "assignment_status": assignment_status,
            "priority": priority,
            "due_at": due_text,
            "source": review.get("source"),
            "evidence_answer_run_ids": review.get("evidence_answer_run_ids") or [],
            "evidence_urls": review.get("evidence_urls") or [],
        }
        notification_id = _stable_id(
            "runtime-notification",
            "entity-alias-assignment-overdue",
            project_id,
            review_id,
            assignment_status,
            due_text,
        )
        return self._insert_runtime_notification(
            cursor=cursor,
            notification_id=notification_id,
            project_id=project_id,
            notification_type="entity_alias_assignment_overdue",
            severity=severity,
            title=title,
            message=message,
            target_type="entity_alias_candidate_review",
            target_id=review_id,
            payload=payload,
            created_by=created_by,
            reason=reason,
            input_refs={
                "entity_alias_candidate_review_ids": [review_id],
                "candidate_ids": [candidate_id],
                "assignment_status": [assignment_status],
                "priority": [priority],
                "due_at": [due_text],
            },
        )

    def _insert_runtime_notification(
        self,
        *,
        cursor: DbCursor,
        notification_id: str,
        project_id: str,
        notification_type: str,
        severity: str,
        title: str,
        message: str,
        target_type: str,
        target_id: str,
        payload: dict[str, Any],
        created_by: str,
        reason: str,
        input_refs: dict[str, Any],
    ) -> tuple[dict[str, Any], tuple[AuditEvent, ...]]:
        now = datetime.now(UTC)
        cursor.execute(
            f"""
            INSERT INTO runtime_notifications (
              id, project_id, notification_type, severity, title, message,
              target_type, target_id, recipient_role, status, payload,
              created_by, created_at, updated_by, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            RETURNING {", ".join(RUNTIME_NOTIFICATION_COLUMNS)}
            """,
            (
                _uuid(notification_id),
                _uuid(project_id),
                notification_type,
                severity,
                title,
                message,
                target_type,
                target_id,
                "project_member",
                "unread",
                _json_payload(payload),
                created_by,
                now,
                created_by,
                now,
            ),
        )
        inserted_row = cursor.fetchone()
        created = inserted_row is not None
        if inserted_row:
            notification = _row_dict(inserted_row, RUNTIME_NOTIFICATION_COLUMNS)
        else:
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_COLUMNS)}
                FROM runtime_notifications
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(notification_id),),
            )
            notification = _row_dict(cursor.fetchone(), RUNTIME_NOTIFICATION_COLUMNS)
        audit_events: list[AuditEvent] = []
        if created:
            audit_events.append(
                build_audit_event(
                    event_type="runtime_notification_created",
                    project_id=project_id,
                    actor_type="worker" if created_by == "runtime-worker" else "user",
                    actor_id=created_by,
                    target_type="runtime_notification",
                    target_id=notification_id,
                    before=None,
                    after=notification,
                    input_refs=input_refs,
                    output_refs={
                        "runtime_notification_ids": [notification_id],
                        "notification_type": [notification_type],
                        "severity": [str(notification.get("severity") or "info")],
                    },
                    method_version="runtime_notification_v1",
                    reason=reason,
                )
            )
        _, delivery_audit_events = self._enqueue_runtime_notification_deliveries(
            cursor=cursor,
            notification=notification,
            updated_by=created_by,
        )
        audit_events.extend(delivery_audit_events)
        return notification, tuple(audit_events)

    def _enqueue_runtime_notification_deliveries(
        self,
        *,
        cursor: DbCursor,
        notification: dict[str, Any],
        updated_by: str,
    ) -> tuple[tuple[dict[str, Any], ...], tuple[AuditEvent, ...]]:
        notification_type = str(notification.get("notification_type") or "").strip().lower()
        severity = str(notification.get("severity") or "info").strip().lower()
        severity_rank = RUNTIME_NOTIFICATION_SEVERITY_ORDER.get(severity, 0)
        cursor.execute(
            f"""
            SELECT {", ".join(RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)}
            FROM runtime_notification_subscriptions
            WHERE project_id = %s
              AND status = %s
              AND channel = ANY(%s)
            ORDER BY updated_at DESC, id DESC
            """,
            (_uuid(str(notification["project_id"])), "active", list(RUNTIME_NOTIFICATION_SUBSCRIPTION_CHANNELS)),
        )
        subscription_rows = _rows_dict(cursor.fetchall(), RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)
        project_email_suppression_hashes: tuple[str, ...] = ()
        if any(str(subscription.get("channel") or "").strip().lower() == "email" for subscription in subscription_rows):
            cursor.execute(
                """
                SELECT recipient_hash
                FROM runtime_notification_email_suppressions
                WHERE project_id = %s AND status = %s
                ORDER BY updated_at DESC, id DESC
                """,
                (_uuid(str(notification["project_id"])), "active"),
            )
            project_email_suppression_candidates: list[str] = []
            for row in cursor.fetchall():
                if not row:
                    continue
                raw_hash = row.get("recipient_hash") if isinstance(row, dict) else row[0]
                recipient_hash = _sha256_hex_or_none(raw_hash, field_name="recipient_hash")
                if recipient_hash:
                    project_email_suppression_candidates.append(recipient_hash)
            project_email_suppression_hashes = tuple(dict.fromkeys(project_email_suppression_candidates))
        queued_deliveries: list[dict[str, Any]] = []
        delivery_audit_events: list[AuditEvent] = []
        for subscription in subscription_rows:
            event_types = {str(event_type).strip().lower() for event_type in subscription.get("event_types", [])}
            threshold = str(subscription.get("severity_threshold") or "info").strip().lower()
            threshold_rank = RUNTIME_NOTIFICATION_SEVERITY_ORDER.get(threshold, 0)
            if notification_type not in event_types:
                continue
            if severity_rank < threshold_rank:
                continue
            channel = str(subscription.get("channel") or "webhook").strip().lower()
            delivery_id = _stable_id(
                "runtime-notification-delivery",
                str(notification["id"]),
                str(subscription["id"]),
            )
            payload = _runtime_notification_delivery_payload(
                notification=notification,
                subscription=subscription,
                notification_type=notification_type,
                severity=severity,
                threshold=threshold,
                channel=channel,
                project_suppression_hashes=project_email_suppression_hashes if channel == "email" else (),
                email_preference_base_url=self.email_preference_base_url,
                email_preference_token_secret=self.email_preference_token_secret,
                email_preference_token_ttl_seconds=self.email_preference_token_ttl_seconds,
            )
            if channel == "email":
                email_payload = payload.get("email") if isinstance(payload.get("email"), dict) else {}
                email_recipients = email_payload.get("to") if isinstance(email_payload.get("to"), list) else []
                email_metadata = email_payload.get("metadata") if isinstance(email_payload.get("metadata"), dict) else {}
                suppressed_hashes = [
                    str(value)
                    for value in email_metadata.get("email_suppressed_recipient_hashes", [])
                    if value
                ]
                if not email_recipients and suppressed_hashes:
                    delivery_audit_events.append(
                        build_audit_event(
                            event_type="runtime_notification_delivery_suppressed",
                            project_id=str(notification["project_id"]),
                            actor_type="worker" if updated_by in {"runtime-worker", "notification-worker"} else "user",
                            actor_id=updated_by,
                            target_type="runtime_notification_subscription",
                            target_id=str(subscription["id"]),
                            before=None,
                            after={
                                "notification_id": str(notification["id"]),
                                "subscription_id": str(subscription["id"]),
                                "channel": "email",
                                "reason": "all recipients suppressed",
                                "email_recipient_count": int(email_metadata.get("email_recipient_count") or 0),
                                "email_filtered_recipient_count": 0,
                            },
                            input_refs={
                                "runtime_notification_ids": [str(notification["id"])],
                                "runtime_notification_subscription_ids": [str(subscription["id"])],
                            },
                            output_refs={
                                "status": ["suppressed"],
                                "email_suppressed_recipient_hashes": suppressed_hashes,
                                "email_configured_suppression_hashes": [
                                    str(value)
                                    for value in email_metadata.get("email_configured_suppression_hashes", [])
                                    if value
                                ],
                            },
                            method_version="runtime_notification_delivery_v1",
                            reason="suppress runtime notification email delivery",
                        )
                    )
                    continue
            cursor.execute(
                f"""
                INSERT INTO runtime_notification_deliveries (
                  id, project_id, notification_id, subscription_id, channel, endpoint_url,
                  status, max_attempts, payload, updated_by, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (notification_id, subscription_id) DO NOTHING
                RETURNING {RUNTIME_NOTIFICATION_DELIVERY_RETURNING}
                """,
                (
                    _uuid(delivery_id),
                    _uuid(str(notification["project_id"])),
                    _uuid(str(notification["id"])),
                    _uuid(str(subscription["id"])),
                    channel,
                    str(subscription["endpoint_url"]),
                    "queued",
                    3,
                    _json_payload(payload),
                    updated_by,
                    datetime.now(UTC),
                ),
            )
            inserted = cursor.fetchone()
            if inserted:
                delivery = _row_dict(inserted, RUNTIME_NOTIFICATION_DELIVERY_COLUMNS)
                queued_deliveries.append(delivery)
                delivery_output_refs = {
                    "runtime_notification_delivery_ids": [str(delivery["id"])],
                    "status": ["queued"],
                }
                if channel == "email":
                    email_payload = payload.get("email") if isinstance(payload.get("email"), dict) else {}
                    email_metadata = email_payload.get("metadata") if isinstance(email_payload.get("metadata"), dict) else {}
                    email_control_hashes = (
                        email_metadata.get("email_control_hashes")
                        if isinstance(email_metadata.get("email_control_hashes"), dict)
                        else {}
                    )
                    email_suppressed_recipient_hashes = [
                        str(value)
                        for value in email_metadata.get("email_suppressed_recipient_hashes", [])
                        if value
                    ]
                    delivery_output_refs.update(
                        {
                            "email_template_versions": [
                                str(email_metadata.get("email_template_version") or "")
                            ],
                            "email_template_hashes": [str(email_metadata.get("email_template_hash") or "")],
                            "email_subject_hashes": [str(email_metadata.get("email_subject_hash") or "")],
                            "email_body_hashes": [str(email_metadata.get("email_body_hash") or "")],
                            "email_reply_to_hashes": [
                                str(email_metadata.get("email_reply_to_hash") or "")
                            ]
                            if email_metadata.get("email_reply_to_hash")
                            else [],
                            "email_control_hashes": [
                                f"{key}:{value}"
                                for key, value in sorted(email_control_hashes.items())
                                if value
                            ],
                            "email_tokenized_unsubscribe_url_hashes": [
                                str(email_metadata.get("email_tokenized_unsubscribe_url_hash") or "")
                            ]
                            if email_metadata.get("email_tokenized_unsubscribe_url_hash")
                            else [],
                            "email_tokenized_preferences_url_hashes": [
                                str(email_metadata.get("email_tokenized_preferences_url_hash") or "")
                            ]
                            if email_metadata.get("email_tokenized_preferences_url_hash")
                            else [],
                            "email_preference_token_hashes": [
                                str(email_metadata.get("email_preference_token_hash") or "")
                            ]
                            if email_metadata.get("email_preference_token_hash")
                            else [],
                            "email_preference_manage_token_hashes": [
                                str(email_metadata.get("email_preference_manage_token_hash") or "")
                            ]
                            if email_metadata.get("email_preference_manage_token_hash")
                            else [],
                            "email_suppressed_recipient_hashes": email_suppressed_recipient_hashes,
                            "email_project_suppression_hashes": [
                                str(value)
                                for value in email_metadata.get("email_project_suppression_hashes", [])
                                if value
                            ],
                            "email_project_suppression_hash_count": [
                                str(email_metadata.get("email_project_suppression_hash_count") or 0)
                            ],
                            "email_filtered_recipient_count": [
                                str(email_metadata.get("email_filtered_recipient_count") or 0)
                            ],
                        }
                    )
                delivery_audit_events.append(
                    build_audit_event(
                        event_type="runtime_notification_delivery_queued",
                        project_id=str(delivery["project_id"]),
                        actor_type="worker" if updated_by in {"runtime-worker", "notification-worker"} else "user",
                        actor_id=updated_by,
                        target_type="runtime_notification_delivery",
                        target_id=str(delivery["id"]),
                        before=None,
                        after=delivery,
                        input_refs={
                            "runtime_notification_ids": [str(notification["id"])],
                            "runtime_notification_subscription_ids": [str(subscription["id"])],
                        },
                        output_refs=delivery_output_refs,
                        method_version="runtime_notification_delivery_v1",
                        reason="queue runtime notification delivery",
                    )
                )
        return tuple(queued_deliveries), tuple(delivery_audit_events)

    def _runtime_notification_from_row(
        self,
        *,
        cursor: DbCursor,
        row: dict[str, Any],
    ) -> RuntimeNotification:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (_uuid(str(row["project_id"])), "runtime_notification", str(row["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeNotification(notification=row, audit_events=audit_events)

    def _runtime_notification_subscription_from_row(
        self,
        *,
        cursor: DbCursor,
        row: dict[str, Any],
    ) -> RuntimeNotificationSubscription:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (_uuid(str(row["project_id"])), "runtime_notification_subscription", str(row["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeNotificationSubscription(subscription=row, audit_events=audit_events)

    def _runtime_notification_delivery_from_row(
        self,
        *,
        cursor: DbCursor,
        row: dict[str, Any],
    ) -> RuntimeNotificationDelivery:
        cursor.execute(
            f"""
            SELECT {", ".join(RUNTIME_NOTIFICATION_COLUMNS)}
            FROM runtime_notifications
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(str(row["notification_id"])),),
        )
        notification_row = cursor.fetchone()
        notification = _row_dict(notification_row, RUNTIME_NOTIFICATION_COLUMNS) if notification_row else None
        cursor.execute(
            f"""
            SELECT {", ".join(RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)}
            FROM runtime_notification_subscriptions
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(str(row["subscription_id"])),),
        )
        subscription_row = cursor.fetchone()
        subscription = (
            _row_dict(subscription_row, RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)
            if subscription_row
            else None
        )
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (_uuid(str(row["project_id"])), "runtime_notification_delivery", str(row["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeNotificationDelivery(
            delivery=row,
            notification=notification,
            subscription=subscription,
            audit_events=audit_events,
        )

    def _runtime_notification_email_feedback_from_row(
        self,
        *,
        cursor: DbCursor,
        feedback_event: dict[str, Any],
        delivery: dict[str, Any] | None = None,
    ) -> RuntimeNotificationEmailFeedback:
        if delivery is None:
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_NOTIFICATION_DELIVERY_COLUMNS)}
                FROM runtime_notification_deliveries
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(str(feedback_event["delivery_id"])),),
            )
            delivery_row = cursor.fetchone()
            delivery = _row_dict(delivery_row, RUNTIME_NOTIFICATION_DELIVERY_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(RUNTIME_NOTIFICATION_COLUMNS)}
            FROM runtime_notifications
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(str(feedback_event["notification_id"])),),
        )
        notification_row = cursor.fetchone()
        notification = _row_dict(notification_row, RUNTIME_NOTIFICATION_COLUMNS) if notification_row else None
        cursor.execute(
            f"""
            SELECT {", ".join(RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)}
            FROM runtime_notification_subscriptions
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(str(feedback_event["subscription_id"])),),
        )
        subscription_row = cursor.fetchone()
        subscription = (
            _row_dict(subscription_row, RUNTIME_NOTIFICATION_SUBSCRIPTION_COLUMNS)
            if subscription_row
            else None
        )
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (_uuid(str(feedback_event["project_id"])), "runtime_notification_delivery", str(feedback_event["delivery_id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeNotificationEmailFeedback(
            feedback_event=feedback_event,
            delivery=delivery,
            notification=notification,
            subscription=subscription,
            audit_events=audit_events,
        )

    def _load_score_snapshot_by_id(
        self,
        *,
        cursor: DbCursor,
        score_snapshot_id: str,
    ) -> RuntimeScoreSnapshot | None:
        cursor.execute(
            f"""
            SELECT {", ".join(VISIBILITY_SCORE_SNAPSHOT_COLUMNS)}
            FROM visibility_score_snapshots
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(score_snapshot_id),),
        )
        snapshot_row = cursor.fetchone()
        if not snapshot_row:
            return None
        snapshot = _row_dict(snapshot_row, VISIBILITY_SCORE_SNAPSHOT_COLUMNS)
        return self._load_runtime_score_snapshot(
            cursor=cursor,
            snapshot=snapshot,
            snapshot_id=str(snapshot["id"]),
        )

    def _load_evidence_run_by_id(
        self,
        *,
        cursor: DbCursor,
        answer_run_id: str,
    ) -> RuntimeEvidenceRun | None:
        cursor.execute(
            f"""
            SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                   pq.text AS prompt_text,
                   pq.intent_type AS prompt_intent_type,
                   pq.priority AS prompt_priority,
                   pq.prompt_version AS prompt_version
            FROM answer_runs ar
            LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
            WHERE ar.id = %s
            LIMIT 1
            """,
            (_uuid(answer_run_id),),
        )
        answer_run_row = cursor.fetchone()
        if not answer_run_row:
            return None
        answer_run = _row_dict(answer_run_row, ANSWER_RUN_READ_COLUMNS)
        return self._load_runtime_evidence_run(
            cursor=cursor,
            answer_run=answer_run,
            answer_run_id=str(answer_run["id"]),
        )

    def _load_action_recommendation_by_id(
        self,
        *,
        cursor: DbCursor,
        action_id: str,
    ) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT {", ".join(ACTION_RECOMMENDATION_COLUMNS)}
            FROM action_recommendations
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(action_id),),
        )
        action_row = cursor.fetchone()
        return _row_dict(action_row, ACTION_RECOMMENDATION_COLUMNS) if action_row else None

    def _load_runtime_content_draft_by_id(
        self,
        *,
        cursor: DbCursor,
        content_draft_id: str,
    ) -> RuntimeContentDraft | None:
        cursor.execute(
            f"""
            SELECT {", ".join(CONTENT_DRAFT_COLUMNS)}
            FROM content_drafts
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(content_draft_id),),
        )
        draft_row = cursor.fetchone()
        if not draft_row:
            return None
        return self._load_runtime_content_draft(
            cursor=cursor,
            draft=_row_dict(draft_row, CONTENT_DRAFT_COLUMNS),
        )

    def _load_audit_event_by_id(
        self,
        *,
        cursor: DbCursor,
        audit_event_id: str,
    ) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE id = %s
            LIMIT 1
            """,
            (_uuid(audit_event_id),),
        )
        event_row = cursor.fetchone()
        return _row_dict(event_row, AUDIT_EVENT_COLUMNS) if event_row else None

    def list_runtime_action_plans(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeActionPlanPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("rs.project_id = %s")
            params.append(_uuid(project_id))
        if status:
            filters.append(
                "EXISTS (SELECT 1 FROM action_recommendations ar WHERE ar.project_id = rs.project_id AND ar.status = %s)"
            )
            params.append(status)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM retest_schedules rs {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(f"rs.{column}" for column in RETEST_SCHEDULE_COLUMNS)}
                FROM retest_schedules rs
                {where_clause}
                ORDER BY rs.created_at DESC, rs.id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            schedules = _rows_dict(cursor.fetchall(), RETEST_SCHEDULE_COLUMNS)
            records = tuple(
                self._load_runtime_action_plan(cursor=cursor, schedule=schedule, status=status)
                for schedule in schedules
            )
        return RuntimeActionPlanPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def export_runtime_action_plans_csv(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        normalized_project_id = project_id.strip()
        if not normalized_project_id:
            raise ValueError("project_id is required")
        normalized_status = status.strip().lower() if status else None
        page = self.list_runtime_action_plans(
            project_id=normalized_project_id,
            status=normalized_status,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_action_plans_csv(page)
        row_count = sum(max(1, len(record.action_recommendations)) for record in page.records)
        filters = {
            "project_id": normalized_project_id,
            "status": normalized_status,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_action_plans_csv",
            filename="runtime-action-plans.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=page.total_count,
            row_count=row_count,
        )

    def update_runtime_action_recommendation(
        self,
        update: RuntimeActionRecommendationUpdateInput,
    ) -> RuntimeActionRecommendationUpdate:
        project_id = update.project_id.strip()
        action_id = update.action_id.strip()
        status = update.status.strip().lower()
        owner_id = update.owner_id.strip() if update.owner_id else None
        visibility_note = update.visibility_note.strip() if update.visibility_note else None
        updated_by = update.updated_by.strip() or "runtime-console"
        reason = update.reason.strip() if update.reason else None
        if not project_id:
            raise ValueError("project_id is required")
        if not action_id:
            raise ValueError("action_id is required")
        if status not in {"open", "in_progress", "done", "blocked", "dismissed"}:
            raise ValueError("action status must be open, in_progress, done, blocked, or dismissed")
        with self.connection.cursor() as cursor:
            before = self._load_action_recommendation_by_id(cursor=cursor, action_id=action_id)
            if not before or str(before.get("project_id")) != project_id:
                raise ValueError("action_recommendation not found")
            cursor.execute(
                f"""
                UPDATE action_recommendations
                SET status = %s,
                    owner_id = %s,
                    customer_visible = COALESCE(%s, customer_visible),
                    visibility_note = %s
                WHERE id = %s AND project_id = %s
                RETURNING {", ".join(ACTION_RECOMMENDATION_COLUMNS)}
                """,
                (
                    status,
                    owner_id,
                    update.customer_visible,
                    visibility_note,
                    _uuid(action_id),
                    _uuid(project_id),
                ),
            )
            after = _row_dict(cursor.fetchone(), ACTION_RECOMMENDATION_COLUMNS)
            if not after:
                raise ValueError("action_recommendation not found")
            audit_event = build_audit_event(
                event_type="action_recommendation_updated",
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="action_recommendation",
                target_id=action_id,
                before=before,
                after=after,
                input_refs={
                    "action_recommendation_ids": [action_id],
                    "status": [status],
                },
                output_refs={"action_recommendation_ids": [action_id]},
                method_version="runtime_action_recommendation_update_v1",
                reason=reason or "update action recommendation",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        return RuntimeActionRecommendationUpdate(
            action_recommendation=after,
            audit_events=(asdict(audit_event),),
        )

    def review_runtime_content_draft(
        self,
        review: RuntimeContentDraftReviewInput,
    ) -> RuntimeContentDraftReview:
        project_id = review.project_id.strip()
        content_draft_id = review.content_draft_id.strip()
        review_status = review.review_status.strip().lower()
        reviewer_id = review.reviewer_id.strip() or "runtime-console"
        decision = review.decision.strip() or "content draft reviewed"
        notes = review.notes.strip() if review.notes else None
        if not project_id:
            raise ValueError("project_id is required")
        if not content_draft_id:
            raise ValueError("content_draft_id is required")
        if review_status not in {"approved", "needs_changes", "rejected", "pending_human_review"}:
            raise ValueError("content draft review_status must be approved, needs_changes, rejected, or pending_human_review")
        human_review = self.save_human_review(
            RuntimeHumanReviewInput(
                project_id=project_id,
                target_type="content_draft",
                target_id=content_draft_id,
                review_status=review_status,
                decision=decision,
                reviewer_id=reviewer_id,
                notes=notes,
                payload=review.payload or {},
            )
        )
        with self.connection.cursor() as cursor:
            runtime_draft = self._load_runtime_content_draft_by_id(
                cursor=cursor,
                content_draft_id=content_draft_id,
            )
        if runtime_draft is None or str(runtime_draft.draft.get("project_id")) != project_id:
            raise ValueError("content draft not found")
        return RuntimeContentDraftReview(
            content_draft=runtime_draft.draft,
            human_review=human_review.human_review,
            audit_events=tuple((*human_review.audit_events, *runtime_draft.audit_events)),
        )

    def backfill_runtime_manual_distribution_record(
        self,
        backfill: RuntimeManualDistributionBackfillInput,
    ) -> RuntimeManualDistributionBackfill:
        project_id = backfill.project_id.strip()
        distribution_record_id = backfill.distribution_record_id.strip()
        target_url = backfill.target_url.strip()
        status = backfill.status.strip().lower() or "url_backfilled"
        checked_by = backfill.checked_by.strip() or "runtime-console"
        notes = backfill.notes.strip() if backfill.notes else None
        if not project_id:
            raise ValueError("project_id is required")
        if not distribution_record_id:
            raise ValueError("distribution_record_id is required")
        if not target_url:
            raise ValueError("target_url is required")
        if not (target_url.startswith("https://") or target_url.startswith("http://")):
            raise ValueError("target_url must be http(s)")
        if status not in {"url_backfilled", "published", "verified", "blocked"}:
            raise ValueError("distribution status must be url_backfilled, published, verified, or blocked")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(MANUAL_DISTRIBUTION_RECORD_COLUMNS)}
                FROM manual_distribution_records
                WHERE id = %s AND project_id = %s
                LIMIT 1
                """,
                (_uuid(distribution_record_id), _uuid(project_id)),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("manual distribution record not found")
            before = _row_dict(row, MANUAL_DISTRIBUTION_RECORD_COLUMNS)
            cursor.execute(
                f"""
                UPDATE manual_distribution_records
                SET target_url = %s,
                    status = %s,
                    submitted_at = COALESCE(submitted_at, now()),
                    checked_at = now(),
                    notes = %s
                WHERE id = %s AND project_id = %s
                RETURNING {", ".join(MANUAL_DISTRIBUTION_RECORD_COLUMNS)}
                """,
                (
                    target_url,
                    status,
                    notes if notes is not None else before.get("notes"),
                    _uuid(distribution_record_id),
                    _uuid(project_id),
                ),
            )
            after = _row_dict(cursor.fetchone(), MANUAL_DISTRIBUTION_RECORD_COLUMNS)
            audit_event = build_audit_event(
                event_type="manual_distribution_record_backfilled",
                project_id=project_id,
                actor_type="user",
                actor_id=checked_by,
                target_type="manual_distribution_record",
                target_id=distribution_record_id,
                before=before,
                after=after,
                input_refs={
                    "manual_distribution_record_ids": [distribution_record_id],
                    "content_draft_ids": [str(after.get("content_draft_id") or "")],
                },
                output_refs={"manual_distribution_record_ids": [distribution_record_id], "status": [status]},
                method_version="manual_distribution_backfill_v1",
                reason="manual URL/proof backfill for Production v1 distribution task",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        return RuntimeManualDistributionBackfill(
            manual_distribution_record=after,
            audit_events=(asdict(audit_event),),
        )

    def record_runtime_alert_event(self, event: RuntimeAlertEventInput) -> RuntimeAlertEvent:
        project_id = event.project_id.strip()
        alert_id = event.alert_id.strip()
        alert_type = event.alert_type.strip()
        source = event.source.strip()
        source_id = event.source_id.strip()
        status = event.status.strip().lower()
        updated_by = event.updated_by.strip() or "runtime-console"
        note = event.note.strip() if event.note else None
        if not project_id:
            raise ValueError("project_id is required")
        if not alert_id:
            raise ValueError("alert_id is required")
        if not alert_type:
            raise ValueError("alert_type is required")
        if not source:
            raise ValueError("source is required")
        if not source_id:
            raise ValueError("source_id is required")
        if status not in RUNTIME_ALERT_EVENT_STATUSES:
            raise ValueError("runtime alert event status must be acknowledged, resolved, snoozed, reopened, or escalated")
        metadata = event.metadata if isinstance(event.metadata, dict) else {}
        event_id = str(uuid4())
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s LIMIT 1", (_uuid(project_id),))
            if not cursor.fetchone():
                raise ValueError("project not found")
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_ALERT_EVENT_COLUMNS)}
                FROM runtime_alert_events
                WHERE alert_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (alert_id,),
            )
            before = _row_dict(cursor.fetchone(), RUNTIME_ALERT_EVENT_COLUMNS)
            cursor.execute(
                f"""
                INSERT INTO runtime_alert_events (
                  id, project_id, alert_id, alert_type, source, source_id, status,
                  updated_by, note, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {", ".join(RUNTIME_ALERT_EVENT_COLUMNS)}
                """,
                (
                    _uuid(event_id),
                    _uuid(project_id),
                    alert_id,
                    alert_type,
                    source,
                    source_id,
                    status,
                    updated_by,
                    note,
                    _json_payload(metadata),
                ),
            )
            after = _row_dict(cursor.fetchone(), RUNTIME_ALERT_EVENT_COLUMNS)
            audit_event = build_audit_event(
                event_type="runtime_alert_event_recorded",
                project_id=project_id,
                actor_type="worker" if updated_by.endswith("-worker") else "user",
                actor_id=updated_by,
                target_type="runtime_alert",
                target_id=alert_id,
                before=before or None,
                after=after,
                input_refs={
                    "runtime_alert_ids": [alert_id],
                    "alert_type": [alert_type],
                    "source": [source],
                    "source_id": [source_id],
                    "status": [status],
                },
                output_refs={"runtime_alert_event_ids": [event_id]},
                method_version="runtime_alert_event_v1",
                reason=note or f"mark runtime alert {status}",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            audit_events = self._load_runtime_alert_audit_events(
                cursor=cursor,
                project_id=project_id,
                alert_id=alert_id,
                source_id=source_id,
            )
        self.connection.commit()
        return RuntimeAlertEvent(alert_event=after, audit_events=audit_events)

    def enqueue_runtime_alert_notifications(
        self,
        *,
        project_id: str,
        alert_type: str | None = None,
        severity: str | None = None,
        created_by: str = "runtime-console",
        reason: str | None = None,
        include_resolved: bool = False,
    ) -> RuntimeAlertNotificationResult:
        project_id = project_id.strip()
        created_by = created_by.strip() or "runtime-console"
        reason = reason.strip() if reason else None
        if not project_id:
            raise ValueError("project_id is required")
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s LIMIT 1", (_uuid(project_id),))
            if not cursor.fetchone():
                raise ValueError("project not found")
        page = self.list_runtime_alerts(
            project_id=project_id,
            alert_type=alert_type.strip() if alert_type else None,
            severity=severity.strip().lower() if severity else None,
            limit=200,
            offset=0,
        )
        inserted_notifications: list[dict[str, Any]] = []
        audit_events: list[AuditEvent] = []
        delivery_count = 0
        skipped_count = 0
        with self.connection.cursor() as cursor:
            for item in page.records:
                latest_status = str(item.management_events[0].get("status") or "").strip().lower() if item.management_events else ""
                if not include_resolved and latest_status in {"resolved", "snoozed"}:
                    skipped_count += 1
                    continue
                alert = dict(item.alert)
                notification, events = self._insert_runtime_alert_notification(
                    cursor=cursor,
                    alert=alert,
                    evidence_refs=item.evidence_refs,
                    related_actions=item.related_actions,
                    latest_management_status=latest_status or None,
                    created_by=created_by,
                    reason=reason or "queue runtime alert notification",
                )
                inserted_notifications.append(notification)
                audit_events.extend(events)
                delivery_count += sum(1 for event in events if event.event_type == "runtime_notification_delivery_queued")
            if audit_events:
                self.save_audit_events(tuple(audit_events), cursor=cursor)
        self.connection.commit()
        return RuntimeAlertNotificationResult(
            project_id=project_id,
            notification_count=len(inserted_notifications),
            delivery_count=delivery_count,
            skipped_count=skipped_count,
            notifications=tuple(inserted_notifications),
            audit_events=tuple(asdict(event) for event in audit_events),
        )

    def list_runtime_alerts(
        self,
        *,
        project_id: str | None = None,
        alert_type: str | None = None,
        severity: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> RuntimeAlertPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        alerts: list[RuntimeAlertItem] = []
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(VISIBILITY_SCORE_SNAPSHOT_COLUMNS)}
                FROM visibility_score_snapshots
                {"WHERE project_id = %s" if project_id else ""}
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (_uuid(project_id),) if project_id else (),
            )
            snapshot = _row_dict(cursor.fetchone(), VISIBILITY_SCORE_SNAPSHOT_COLUMNS)
            if not snapshot:
                return RuntimeAlertPage(total_count=0, limit=limit, offset=offset, records=())

            selected_project_id = str(snapshot["project_id"])
            snapshot_id = str(snapshot["id"])
            cursor.execute(
                f"""
                SELECT {", ".join(SCORE_CONTRIBUTION_COLUMNS)}
                FROM score_contributions
                WHERE score_snapshot_id = %s
                ORDER BY component_name ASC, created_at ASC
                """,
                (_uuid(snapshot_id),),
            )
            contributions = _rows_dict(cursor.fetchall(), SCORE_CONTRIBUTION_COLUMNS)
            contributions_by_name = _score_contribution_by_name(contributions)
            cursor.execute(
                f"""
                SELECT {", ".join(SOURCE_GAP_COLUMNS)}
                FROM source_gaps
                WHERE project_id = %s
                ORDER BY expected_weight DESC, source_type ASC, gap_type ASC
                """,
                (_uuid(selected_project_id),),
            )
            source_gaps = _rows_dict(cursor.fetchall(), SOURCE_GAP_COLUMNS)
            cursor.execute(
                f"""
                SELECT {", ".join(COMPETITOR_BENCHMARK_COLUMNS)}
                FROM competitor_benchmarks
                WHERE project_id = %s
                ORDER BY competitor_name ASC
                """,
                (_uuid(selected_project_id),),
            )
            competitor_benchmarks = _rows_dict(cursor.fetchall(), COMPETITOR_BENCHMARK_COLUMNS)
            cursor.execute(
                f"""
                SELECT {", ".join(ACTION_RECOMMENDATION_COLUMNS)}
                FROM action_recommendations
                WHERE project_id = %s
                ORDER BY priority ASC, next_check_date ASC, id ASC
                """,
                (_uuid(selected_project_id),),
            )
            actions = _rows_dict(cursor.fetchall(), ACTION_RECOMMENDATION_COLUMNS)
            answer_run_ids = tuple(str(value) for value in snapshot.get("answer_run_ids") or ())
            analyses: tuple[dict[str, Any], ...] = ()
            if answer_run_ids:
                cursor.execute(
                    f"""
                    SELECT {", ".join(ANSWER_ANALYSIS_READ_COLUMNS)}
                    FROM answer_analyses
                    WHERE answer_run_id = ANY(%s::uuid[])
                    ORDER BY created_at DESC, id DESC
                    """,
                    (_uuid_array(answer_run_ids),),
                )
                latest_by_answer_run: dict[str, dict[str, Any]] = {}
                for analysis in _rows_dict(cursor.fetchall(), ANSWER_ANALYSIS_READ_COLUMNS):
                    latest_by_answer_run.setdefault(str(analysis.get("answer_run_id")), analysis)
                analyses = tuple(latest_by_answer_run.values())
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE project_id = %s
                  AND target_type = %s
                  AND target_id = %s
                ORDER BY created_at DESC
                LIMIT 5
                """,
                (_uuid(selected_project_id), "visibility_score_snapshot", snapshot_id),
            )
            score_audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)

        mention_rate = float(snapshot.get("mention_rate") or 0.0)
        recommendation_rate = float(snapshot.get("recommendation_rate") or 0.0)
        snapshot_created_at = snapshot.get("created_at")
        if mention_rate < 0.5:
            mention_contribution = contributions_by_name.get("MentionScore", {})
            alerts.append(
                RuntimeAlertItem(
                    alert={
                        "id": _stable_id("runtime-alert", selected_project_id, snapshot_id, "brand_absent"),
                        "project_id": selected_project_id,
                        "alert_type": "brand_absent",
                        "severity": "high" if mention_rate < 0.35 else "medium",
                        "title": "Brand mention coverage is below threshold",
                        "summary": "AI answers are not mentioning the target brand often enough for high-intent prompts.",
                        "metric_name": "mention_rate",
                        "metric_value": mention_rate,
                        "threshold": 0.5,
                        "rule_version": "runtime_alerts_v1",
                        "source": "visibility_score_snapshot",
                        "source_id": snapshot_id,
                        "created_at": snapshot_created_at,
                    },
                    evidence_refs=(
                        {"target_type": "visibility_score_snapshot", "target_id": snapshot_id},
                        {"target_type": "score_contribution", "target_id": str(mention_contribution.get("id") or "")},
                        *_answer_run_refs(snapshot.get("answer_run_ids")),
                    ),
                    related_actions=_first_matching_action(actions, source_gap_type="low_mention_rate"),
                    audit_events=score_audit_events,
                )
            )
        if recommendation_rate < 0.35:
            recommendation_contribution = contributions_by_name.get("RecommendationScore", {})
            alerts.append(
                RuntimeAlertItem(
                    alert={
                        "id": _stable_id("runtime-alert", selected_project_id, snapshot_id, "low_recommendation_rate"),
                        "project_id": selected_project_id,
                        "alert_type": "low_recommendation_rate",
                        "severity": "high" if recommendation_rate < 0.2 else "medium",
                        "title": "Recommendation rate is below threshold",
                        "summary": "The brand is present in some answers but not recommended strongly enough.",
                        "metric_name": "recommendation_rate",
                        "metric_value": recommendation_rate,
                        "threshold": 0.35,
                        "rule_version": "runtime_alerts_v1",
                        "source": "visibility_score_snapshot",
                        "source_id": snapshot_id,
                        "created_at": snapshot_created_at,
                    },
                    evidence_refs=(
                        {"target_type": "visibility_score_snapshot", "target_id": snapshot_id},
                        {"target_type": "score_contribution", "target_id": str(recommendation_contribution.get("id") or "")},
                        *_answer_run_refs(snapshot.get("answer_run_ids")),
                    ),
                    related_actions=_first_matching_action(actions, source_gap_type="low_recommendation_rate"),
                    audit_events=score_audit_events,
                )
            )
        for gap in source_gaps:
            expected_weight = float(gap.get("expected_weight") or 0.0)
            alerts.append(
                RuntimeAlertItem(
                    alert={
                        "id": _stable_id("runtime-alert", selected_project_id, gap.get("id"), "source_gap"),
                        "project_id": selected_project_id,
                        "alert_type": "source_gap",
                        "severity": "high" if expected_weight >= 0.9 else "medium",
                        "title": f"{gap.get('source_type')} source gap",
                        "summary": gap.get("recommendation"),
                        "metric_name": "expected_source_weight",
                        "metric_value": expected_weight,
                        "threshold": 0.75,
                        "rule_version": "runtime_alerts_v1",
                        "source": "source_gap",
                        "source_id": str(gap.get("id")),
                        "created_at": gap.get("created_at"),
                    },
                    evidence_refs=(
                        {"target_type": "source_gap", "target_id": str(gap.get("id"))},
                        {"target_type": "visibility_score_snapshot", "target_id": snapshot_id},
                    ),
                    related_actions=_first_matching_action(actions, source_gap_type=str(gap.get("gap_type") or "")),
                    audit_events=score_audit_events,
                )
            )
        for benchmark in competitor_benchmarks:
            payload = benchmark.get("payload") if isinstance(benchmark.get("payload"), dict) else {}
            competitor_rate = float(payload.get("mention_rate") or 0.0) if isinstance(payload, dict) else 0.0
            if competitor_rate <= mention_rate:
                continue
            alerts.append(
                RuntimeAlertItem(
                    alert={
                        "id": _stable_id("runtime-alert", selected_project_id, benchmark.get("id"), "competitor_pressure"),
                        "project_id": selected_project_id,
                        "alert_type": "competitor_pressure",
                        "severity": "critical" if competitor_rate - mention_rate >= 0.25 else "high",
                        "title": f"{benchmark.get('competitor_name')} is out-mentioning the brand",
                        "summary": "A tracked competitor has a higher mention rate than the target brand in the current evidence window.",
                        "metric_name": "competitor_minus_brand_mention_rate",
                        "metric_value": round(competitor_rate - mention_rate, 4),
                        "threshold": 0.0,
                        "rule_version": "runtime_alerts_v1",
                        "source": "competitor_benchmark",
                        "source_id": str(benchmark.get("id")),
                        "created_at": benchmark.get("created_at"),
                    },
                    evidence_refs=(
                        {"target_type": "competitor_benchmark", "target_id": str(benchmark.get("id"))},
                        {"target_type": "visibility_score_snapshot", "target_id": snapshot_id},
                        *_answer_run_refs(benchmark.get("answer_run_ids")),
                    ),
                    related_actions=(),
                    audit_events=score_audit_events,
                )
            )
        negative_analyses = tuple(
            analysis
            for analysis in analyses
            if (sentiment_score := _analysis_sentiment_score(analysis)) is not None and sentiment_score < 40.0
        )
        if negative_analyses:
            lowest_negative = min(negative_analyses, key=lambda item: _analysis_sentiment_score(item) or 100.0)
            lowest_score = float(_analysis_sentiment_score(lowest_negative) or 0.0)
            related_answer_run_ids = [str(analysis.get("answer_run_id")) for analysis in negative_analyses if analysis.get("answer_run_id")]
            alerts.append(
                RuntimeAlertItem(
                    alert={
                        "id": _stable_id(
                            "runtime-alert",
                            selected_project_id,
                            snapshot_id,
                            "negative_sentiment",
                            str(lowest_negative.get("id")),
                        ),
                        "project_id": selected_project_id,
                        "alert_type": "negative_sentiment",
                        "severity": "critical" if lowest_score < 25.0 else "high",
                        "title": "Negative sentiment detected in AI answers",
                        "summary": f"{len(negative_analyses)} answer analysis record(s) have sentiment below the risk threshold.",
                        "metric_name": "minimum_sentiment_score",
                        "metric_value": lowest_score,
                        "threshold": 40.0,
                        "rule_version": "runtime_alerts_v1",
                        "source": "answer_analysis",
                        "source_id": str(lowest_negative.get("id")),
                        "created_at": lowest_negative.get("created_at") or snapshot_created_at,
                    },
                    evidence_refs=(
                        {"target_type": "visibility_score_snapshot", "target_id": snapshot_id},
                        {"target_type": "answer_analysis", "target_id": str(lowest_negative.get("id"))},
                        *_answer_run_refs(related_answer_run_ids),
                    ),
                    related_actions=(),
                    audit_events=score_audit_events,
                )
            )
        if alert_type:
            alerts = [item for item in alerts if item.alert.get("alert_type") == alert_type]
        if severity:
            alerts = [item for item in alerts if item.alert.get("severity") == severity]
        alerts = [
            RuntimeAlertItem(
                alert=item.alert,
                evidence_refs=item.evidence_refs,
                related_actions=item.related_actions,
                audit_events=item.audit_events,
                management_events=self._load_runtime_alert_events(
                    project_id=selected_project_id,
                    alert_id=str(item.alert.get("id") or ""),
                    source_id=str(item.alert.get("source_id") or ""),
                ),
            )
            for item in alerts
        ]
        alerts.sort(
            key=lambda item: (
                _alert_severity(str(item.alert.get("severity"))),
                str(item.alert.get("alert_type") or ""),
                str(item.alert.get("source_id") or ""),
            )
        )
        total_count = len(alerts)
        paged = tuple(alerts[offset : offset + limit])
        return RuntimeAlertPage(total_count=total_count, limit=limit, offset=offset, records=paged)

    def export_runtime_alerts_csv(
        self,
        *,
        project_id: str,
        alert_type: str | None = None,
        severity: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        normalized_project_id = project_id.strip()
        if not normalized_project_id:
            raise ValueError("project_id is required")
        normalized_alert_type = alert_type.strip() if alert_type else None
        normalized_severity = severity.strip().lower() if severity else None
        page = self.list_runtime_alerts(
            project_id=normalized_project_id,
            alert_type=normalized_alert_type,
            severity=normalized_severity,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_alerts_csv(page)
        filters = {
            "project_id": normalized_project_id,
            "alert_type": normalized_alert_type,
            "severity": normalized_severity,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_alerts_csv",
            filename="runtime-alerts.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=page.total_count,
            row_count=len(page.records),
        )

    def _load_runtime_alert_events(
        self,
        *,
        project_id: str,
        alert_id: str,
        source_id: str,
        limit: int = 5,
    ) -> tuple[dict[str, Any], ...]:
        if not alert_id:
            return ()
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_ALERT_EVENT_COLUMNS)}
                FROM runtime_alert_events
                WHERE project_id = %s
                  AND (alert_id = %s OR source_id = %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (_uuid(project_id), alert_id, source_id, max(1, min(limit, 20))),
            )
            return _rows_dict(cursor.fetchall(), RUNTIME_ALERT_EVENT_COLUMNS)

    def _load_runtime_alert_audit_events(
        self,
        *,
        cursor: DbCursor,
        project_id: str,
        alert_id: str,
        source_id: str,
        limit: int = 5,
    ) -> tuple[dict[str, Any], ...]:
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s
              AND target_type = %s
              AND (target_id = %s OR target_id = %s)
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (_uuid(project_id), "runtime_alert", alert_id, source_id, max(1, min(limit, 20))),
        )
        return _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)

    def _load_runtime_action_plan(
        self,
        *,
        cursor: DbCursor,
        schedule: dict[str, Any],
        status: str | None,
    ) -> RuntimeActionPlan:
        action_filters = ["project_id = %s"]
        action_params: list[object] = [_uuid(str(schedule["project_id"]))]
        if status:
            action_filters.append("status = %s")
            action_params.append(status)
        cursor.execute(
            f"""
            SELECT {", ".join(ACTION_RECOMMENDATION_COLUMNS)}
            FROM action_recommendations
            WHERE {" AND ".join(action_filters)}
            ORDER BY priority ASC, next_check_date ASC, id ASC
            """,
            tuple(action_params),
        )
        actions = _rows_dict(cursor.fetchall(), ACTION_RECOMMENDATION_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(RETEST_COMPARISON_COLUMNS)}
            FROM retest_comparisons
            WHERE project_id = %s
            ORDER BY created_at DESC, id DESC
            """,
            (_uuid(str(schedule["project_id"])),),
        )
        comparisons = _rows_dict(cursor.fetchall(), RETEST_COMPARISON_COLUMNS)
        answer_runs: list[dict[str, Any]] = []
        for answer_run_id in tuple(str(value) for value in schedule["answer_run_ids"]):
            cursor.execute(
                f"""
                SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                       pq.text AS prompt_text,
                       pq.intent_type AS prompt_intent_type,
                       pq.priority AS prompt_priority,
                       pq.prompt_version AS prompt_version
                FROM answer_runs ar
                LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
                WHERE ar.id = %s
                LIMIT 1
                """,
                (_uuid(answer_run_id),),
            )
            answer_run_row = cursor.fetchone()
            if answer_run_row:
                answer_runs.append(_row_dict(answer_run_row, ANSWER_RUN_READ_COLUMNS))
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE target_type = %s AND target_id = %s
            ORDER BY created_at ASC
            """,
            ("action_plan", str(schedule["id"])),
        )
        audit_events = list(_rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS))
        for comparison in comparisons:
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE target_type = %s AND target_id = %s
                ORDER BY created_at ASC
                """,
                ("retest_comparison", str(comparison["id"])),
            )
            audit_events.extend(_rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS))
        return RuntimeActionPlan(
            retest_schedule=schedule,
            action_recommendations=actions,
            retest_comparisons=comparisons,
            answer_runs=tuple(answer_runs),
            audit_events=tuple(audit_events),
        )

    def list_runtime_content_engines(
        self,
        *,
        project_id: str | None = None,
        review_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeContentEnginePage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("cd.project_id = %s")
            params.append(_uuid(project_id))
        if review_status:
            filters.append("cd.review_status = %s")
            params.append(review_status)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(DISTINCT cd.project_id) FROM content_drafts cd {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT cd.project_id
                FROM content_drafts cd
                {where_clause}
                GROUP BY cd.project_id
                ORDER BY max(cd.created_at) DESC, cd.project_id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            project_rows = cursor.fetchall()
            project_ids = tuple(str(row["project_id"] if isinstance(row, dict) else row[0]) for row in project_rows)
            records = tuple(
                self._load_runtime_content_engine(
                    cursor=cursor,
                    project_id=content_project_id,
                    review_status=review_status,
                )
                for content_project_id in project_ids
            )
        return RuntimeContentEnginePage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def export_runtime_content_engines_csv(
        self,
        *,
        project_id: str,
        review_status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> RuntimeEvidenceExport:
        normalized_project_id = project_id.strip()
        if not normalized_project_id:
            raise ValueError("project_id is required")
        normalized_review_status = review_status.strip() if review_status else None
        page = self.list_runtime_content_engines(
            project_id=normalized_project_id,
            review_status=normalized_review_status,
            limit=limit,
            offset=offset,
        )
        content = _render_runtime_content_engines_csv(page)
        row_count = sum(max(1, len(record.content_drafts)) for record in page.records)
        filters = {
            "project_id": normalized_project_id,
            "review_status": normalized_review_status,
            "limit": page.limit,
            "offset": page.offset,
        }
        return RuntimeEvidenceExport(
            export_type="runtime_content_engines_csv",
            filename="runtime-content-engines.csv",
            media_type="text/csv; charset=utf-8",
            content=content,
            content_hash=_artifact_hash(content),
            filters={key: value for key, value in filters.items() if value is not None},
            total_count=page.total_count,
            row_count=row_count,
        )

    def search_runtime_knowledge_facts(
        self,
        *,
        project_id: str,
        query: str,
        market_code: str = "AU",
        city: str | None = None,
        embedding_model: str = KNOWLEDGE_EMBEDDING_MODEL,
        limit: int = 10,
        offset: int = 0,
    ) -> RuntimeKnowledgeSearchPage:
        project_id = project_id.strip()
        query = query.strip()
        market_code = market_code.strip() or "AU"
        embedding_model = embedding_model.strip() or KNOWLEDGE_EMBEDDING_MODEL
        if not project_id:
            raise ValueError("project_id is required")
        if not query:
            raise ValueError("query is required")
        limit = max(1, min(limit, 50))
        offset = max(0, offset)
        query_vector = _vector_literal(embed_knowledge_text(query))
        filters = [
            "kf.project_id = %s",
            "kf.status = %s",
            "kfe.embedding_model = %s",
            "(kf.market_code = %s OR kf.market_code = %s)",
        ]
        params: list[object] = [
            _uuid(project_id),
            KNOWLEDGE_FACT_APPROVED_STATUS,
            embedding_model,
            market_code,
            "GLOBAL",
        ]
        if city:
            filters.append("(kf.city IS NULL OR kf.city = %s)")
            params.append(city)
        where_clause = f"WHERE {' AND '.join(filters)}"
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*)
                FROM localized_knowledge_facts kf
                JOIN knowledge_fact_embeddings kfe ON kfe.knowledge_fact_id = kf.id
                {where_clause}
                """,
                tuple(params),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(f"kf.{column}" for column in LOCALIZED_KNOWLEDGE_FACT_COLUMNS)},
                       kfe.embedding_model AS embedding_model,
                       (1 - (kfe.embedding <=> %s::vector)) AS vector_score,
                       CASE WHEN kf.market_code = %s THEN false ELSE true END AS fallback_used
                FROM localized_knowledge_facts kf
                JOIN knowledge_fact_embeddings kfe ON kfe.knowledge_fact_id = kf.id
                {where_clause}
                ORDER BY
                  CASE WHEN kf.market_code = %s THEN 0 ELSE 1 END,
                  kfe.embedding <=> %s::vector,
                  kf.confidence DESC,
                  kf.id ASC
                LIMIT %s OFFSET %s
                """,
                (query_vector, market_code, *params, market_code, query_vector, limit, offset),
            )
            search_columns = (*LOCALIZED_KNOWLEDGE_FACT_COLUMNS, "embedding_model", "vector_score", "fallback_used")
            rows = _rows_dict(cursor.fetchall(), search_columns)
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE project_id = %s AND target_type = %s AND target_id = %s
                ORDER BY created_at DESC
                LIMIT 5
                """,
                (_uuid(project_id), "knowledge_fact_embedding_index", project_id),
            )
            audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        records = tuple(
            RuntimeKnowledgeSearchResult(
                fact={column: row[column] for column in LOCALIZED_KNOWLEDGE_FACT_COLUMNS},
                score=round(float(row.get("vector_score") or 0.0), 6),
                fallback_used=bool(row.get("fallback_used")),
                embedding_model=str(row.get("embedding_model") or embedding_model),
            )
            for row in rows
        )
        return RuntimeKnowledgeSearchPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            query=query,
            market_code=market_code,
            city=city,
            embedding_model=embedding_model,
            records=records,
            audit_events=audit_events,
        )

    def import_runtime_knowledge_facts_csv(
        self,
        knowledge_import: RuntimeKnowledgeFactImportInput,
    ) -> RuntimeKnowledgeFactImportResult:
        project_id = knowledge_import.project_id.strip()
        imported_by = knowledge_import.imported_by.strip() or "runtime-console"
        max_rows = max(1, min(knowledge_import.max_rows, 200))
        default_market_code = (knowledge_import.default_market_code or "AU").strip().upper() or "AU"
        source_format = (knowledge_import.source_format or "csv").strip().lower()
        source_filename = (knowledge_import.source_filename or "").strip() or None
        if not project_id:
            raise ValueError("project_id is required")
        facts = _parse_knowledge_fact_import_csv(
            project_id=project_id,
            csv_content=knowledge_import.csv_content,
            max_rows=max_rows,
            default_market_code=default_market_code,
        )
        now = datetime.now(UTC)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, market_code
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            project_row = cursor.fetchone()
            if not project_row:
                raise ValueError("project not found")
            fact_models = tuple(
                LocalizedKnowledgeFact(
                    id=_stable_id(
                        "runtime-knowledge-fact-import",
                        project_id,
                        fact["market_code"],
                        fact["fact_type"],
                        fact["subject"],
                        fact["predicate"],
                        fact["object_value"],
                        fact.get("city") or "global",
                    ),
                    project_id=project_id,
                    market_code=fact["market_code"],
                    fact_type=fact["fact_type"],
                    subject=fact["subject"],
                    predicate=fact["predicate"],
                    object_value=fact["object_value"],
                    city=fact.get("city"),
                    evidence_source_id=None,
                    confidence=float(fact["confidence"]),
                    status=str(fact["status"]),
                    valid_from=now,
                    valid_until=None,
                )
                for fact in facts
            )
            fact_ids: list[str] = []
            for fact in fact_models:
                fact_ids.append(fact.id)
                cursor.execute(
                    """
                    INSERT INTO localized_knowledge_facts (
                      id, project_id, market_code, fact_type, subject, predicate, object_value,
                      city, evidence_source_id, confidence, status, valid_from, valid_until
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      market_code = EXCLUDED.market_code,
                      fact_type = EXCLUDED.fact_type,
                      subject = EXCLUDED.subject,
                      predicate = EXCLUDED.predicate,
                      object_value = EXCLUDED.object_value,
                      city = EXCLUDED.city,
                      confidence = EXCLUDED.confidence,
                      status = EXCLUDED.status,
                      valid_from = EXCLUDED.valid_from,
                      valid_until = EXCLUDED.valid_until
                    """,
                    (
                        _uuid(fact.id),
                        _uuid(fact.project_id),
                        fact.market_code,
                        fact.fact_type,
                        fact.subject,
                        fact.predicate,
                        fact.object_value,
                        fact.city,
                        _uuid(fact.evidence_source_id),
                        fact.confidence,
                        fact.status,
                        _datetime(fact.valid_from),
                        _datetime(fact.valid_until),
                    ),
                )
            embedding_audit = self._index_knowledge_fact_embeddings(
                cursor=cursor,
                facts=fact_models,
                actor_id=imported_by,
            )
            after = {
                "project_id": project_id,
                "knowledge_fact_count": len(fact_models),
                "knowledge_fact_ids": fact_ids,
                "source_format": source_format,
                "source_filename": source_filename,
                "default_market_code": default_market_code,
            }
            import_audit = build_audit_event(
                event_type="runtime_knowledge_facts_imported",
                project_id=project_id,
                actor_type="user",
                actor_id=imported_by,
                target_type="knowledge_fact_import",
                target_id=_stable_id("knowledge-fact-import", project_id, imported_by, len(fact_models)),
                before={"project_id": project_id, "imported_knowledge_fact_count": 0},
                after=after,
                input_refs={
                    "csv_sha256": [_artifact_hash(knowledge_import.csv_content)],
                    "source_format": source_format,
                    "source_filename": source_filename,
                },
                output_refs={"knowledge_fact_ids": fact_ids},
                method_version=f"runtime_knowledge_fact_import_{source_format}_v1",
                reason=f"import runtime knowledge facts from {source_format}",
            )
            audit_events_to_save = (embedding_audit, import_audit) if embedding_audit else (import_audit,)
            self.save_audit_events(audit_events_to_save, cursor=cursor)
            imported_rows: list[dict[str, Any]] = []
            for fact_id in fact_ids:
                cursor.execute(
                    f"""
                    SELECT {", ".join(LOCALIZED_KNOWLEDGE_FACT_COLUMNS)}
                    FROM localized_knowledge_facts
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (_uuid(fact_id),),
                )
                row = cursor.fetchone()
                if row:
                    imported_rows.append(_row_dict(row, LOCALIZED_KNOWLEDGE_FACT_COLUMNS))
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE project_id = %s AND target_type IN (%s, %s)
                ORDER BY created_at DESC
                LIMIT 5
                """,
                (_uuid(project_id), "knowledge_fact_import", "knowledge_fact_embedding_index"),
            )
            audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        self.connection.commit()
        return RuntimeKnowledgeFactImportResult(
            knowledge_fact_import=after,
            knowledge_facts=tuple(imported_rows),
            audit_events=audit_events,
        )

    def create_runtime_knowledge_document(
        self,
        document_input: RuntimeKnowledgeDocumentInput,
    ) -> RuntimeKnowledgeDocument:
        project_id = document_input.project_id.strip()
        imported_by = document_input.imported_by.strip() or "runtime-console"
        source_type = document_input.source_type.strip().lower()
        source_url = (document_input.source_url or "").strip() or None
        raw_text = (document_input.raw_text or "").strip()
        title = (document_input.title or "").strip()
        if not project_id:
            raise ValueError("project_id is required")
        if source_type not in {"csv", "url", "web_text"}:
            raise ValueError("source_type must be csv, url, or web_text")
        if source_type == "url" and not source_url:
            raise ValueError("source_url is required for url knowledge documents")
        if source_type != "url" and not raw_text:
            raise ValueError("raw_text is required for csv or web_text knowledge documents")
        normalized_url = normalize_knowledge_url(source_url) if source_type == "url" and source_url else source_url
        content_hash = _artifact_hash(raw_text or source_url or "")
        document_id = stable_knowledge_id("knowledge-document", project_id, source_type, normalized_url or content_hash)
        now = datetime.now(UTC)
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s LIMIT 1", (_uuid(project_id),))
            if not cursor.fetchone():
                raise ValueError("project not found")
            cursor.execute(
                """
                INSERT INTO knowledge_documents (
                  id, project_id, source_type, normalized_url, source_url, title, raw_text,
                  content_hash, status, error_reason, metadata, imported_by, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  title = EXCLUDED.title,
                  raw_text = EXCLUDED.raw_text,
                  content_hash = EXCLUDED.content_hash,
                  status = EXCLUDED.status,
                  metadata = EXCLUDED.metadata,
                  imported_by = EXCLUDED.imported_by,
                  updated_at = now()
                """,
                (
                    _uuid(document_id),
                    _uuid(project_id),
                    source_type,
                    normalized_url,
                    source_url,
                    title or source_url or "Knowledge document",
                    raw_text,
                    content_hash,
                    DOCUMENT_STATUS_QUEUED if source_type == "url" else DOCUMENT_STATUS_CRAWLED,
                    _json_payload(document_input.metadata),
                    imported_by,
                    _datetime(now),
                    _datetime(now),
                ),
            )
            cursor.execute(
                f"SELECT {', '.join(KNOWLEDGE_DOCUMENT_COLUMNS)} FROM knowledge_documents WHERE id = %s LIMIT 1",
                (_uuid(document_id),),
            )
            document = _row_dict(cursor.fetchone(), KNOWLEDGE_DOCUMENT_COLUMNS)
            audit_event = build_audit_event(
                event_type="knowledge.document_imported",
                project_id=project_id,
                actor_type="user",
                actor_id=imported_by,
                target_type="knowledge_document",
                target_id=document_id,
                before=None,
                after=document,
                input_refs={"source_url": [source_url] if source_url else [], "source_type": source_type},
                output_refs={"knowledge_document_ids": [document_id]},
                method_version="runtime_knowledge_document_import_v1",
                reason="import knowledge source document for GEO knowledge application",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE project_id = %s AND target_type = %s AND target_id = %s
                ORDER BY created_at DESC
                LIMIT 5
                """,
                (_uuid(project_id), "knowledge_document", document_id),
            )
            audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        self.connection.commit()
        return RuntimeKnowledgeDocument(knowledge_document=document, audit_events=audit_events)

    def crawl_runtime_knowledge_document(
        self,
        crawl_input: RuntimeKnowledgeDocumentCrawlInput,
    ) -> RuntimeKnowledgeDocument:
        project_id = crawl_input.project_id.strip()
        document_id = crawl_input.knowledge_document_id.strip()
        crawled_by = crawl_input.crawled_by.strip() or "runtime-console"
        if not project_id:
            raise ValueError("project_id is required")
        if not document_id:
            raise ValueError("knowledge_document_id is required")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(KNOWLEDGE_DOCUMENT_COLUMNS)}
                FROM knowledge_documents
                WHERE id = %s AND project_id = %s
                FOR UPDATE
                """,
                (_uuid(document_id), _uuid(project_id)),
            )
            before_row = cursor.fetchone()
            if not before_row:
                raise ValueError("knowledge document not found")
            before = _row_dict(before_row, KNOWLEDGE_DOCUMENT_COLUMNS)
            source_url = str(before.get("source_url") or "")
            if not source_url:
                raise ValueError("knowledge document has no source_url")
            job_id = stable_knowledge_id("knowledge-crawl-job", project_id, document_id, datetime.now(UTC).isoformat())
            cursor.execute(
                """
                INSERT INTO knowledge_generation_jobs (
                  id, project_id, job_type, status, request_payload, step_events, generation_model,
                  generation_prompt_version, requested_by, started_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                """,
                (
                    _uuid(job_id),
                    _uuid(project_id),
                    "crawl",
                    "running",
                    _json_payload({"knowledge_document_id": document_id, "source_url": source_url}),
                    _json_payload([{"step": "crawl_started", "adapter": "crawl4ai_adapter_v1"}]),
                    DEEPSEEK_DEFAULT_MODEL,
                    KNOWLEDGE_APPLICATION_PIPELINE_VERSION,
                    crawled_by,
                ),
            )
            try:
                crawl_result = crawl_public_knowledge_url(
                    source_url=source_url,
                    max_bytes=crawl_input.max_bytes,
                    timeout_seconds=crawl_input.timeout_seconds,
                )
                cursor.execute(
                    """
                    SELECT COALESCE(max(version_number), 0) + 1 AS next_version_number
                    FROM knowledge_document_versions
                    WHERE knowledge_document_id = %s
                    """,
                    (_uuid(document_id),),
                )
                version_number_row = cursor.fetchone()
                version_number = int(
                    version_number_row[0]
                    if not isinstance(version_number_row, dict)
                    else version_number_row["next_version_number"]
                )
                version_id = stable_knowledge_id("knowledge-document-version", document_id, version_number, crawl_result.content_hash)
                cursor.execute(
                    """
                    INSERT INTO knowledge_document_versions (
                      id, project_id, knowledge_document_id, version_number, normalized_url, source_url,
                      title, raw_text, content_hash, status, crawl_adapter_version, byte_size,
                      metadata, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(version_id),
                        _uuid(project_id),
                        _uuid(document_id),
                        version_number,
                        crawl_result.normalized_url,
                        crawl_result.source_url,
                        crawl_result.title,
                        crawl_result.markdown,
                        crawl_result.content_hash,
                        DOCUMENT_STATUS_CRAWLED,
                        crawl_result.adapter_version,
                        crawl_result.byte_size,
                        _json_payload(
                            {
                                "status_code": crawl_result.status_code,
                                "content_type": crawl_result.content_type,
                                "max_pages": crawl_input.max_pages,
                            }
                        ),
                        crawled_by,
                    ),
                )
                cursor.execute(
                    """
                    UPDATE knowledge_documents
                    SET normalized_url = %s,
                        title = %s,
                        raw_text = %s,
                        content_hash = %s,
                        status = %s,
                        error_reason = NULL,
                        updated_at = now()
                    WHERE id = %s AND project_id = %s
                    """,
                    (
                        crawl_result.normalized_url,
                        crawl_result.title,
                        crawl_result.markdown,
                        crawl_result.content_hash,
                        DOCUMENT_STATUS_CRAWLED,
                        _uuid(document_id),
                        _uuid(project_id),
                    ),
                )
                cursor.execute(
                    """
                    UPDATE knowledge_generation_jobs
                    SET status = %s,
                        completed_at = now(),
                        updated_at = now(),
                        raw_output_hash = %s,
                        step_events = %s
                    WHERE id = %s
                    """,
                    (
                        "succeeded",
                        _artifact_hash(crawl_result.markdown),
                        _json_payload(
                            [
                                {"step": "crawl_started", "adapter": "crawl4ai_adapter_v1"},
                                {"step": "crawl_succeeded", "version_id": version_id},
                            ]
                        ),
                        _uuid(job_id),
                    ),
                )
                error_reason = None
            except ValueError as exc:
                error_reason = str(exc)
                cursor.execute(
                    """
                    UPDATE knowledge_documents
                    SET status = %s, error_reason = %s, updated_at = now()
                    WHERE id = %s AND project_id = %s
                    """,
                    (DOCUMENT_STATUS_FAILED, error_reason, _uuid(document_id), _uuid(project_id)),
                )
                cursor.execute(
                    """
                    UPDATE knowledge_generation_jobs
                    SET status = %s, error_reason = %s, completed_at = now(), updated_at = now()
                    WHERE id = %s
                    """,
                    ("failed", error_reason, _uuid(job_id)),
                )
            cursor.execute(
                f"SELECT {', '.join(KNOWLEDGE_DOCUMENT_COLUMNS)} FROM knowledge_documents WHERE id = %s LIMIT 1",
                (_uuid(document_id),),
            )
            after = _row_dict(cursor.fetchone(), KNOWLEDGE_DOCUMENT_COLUMNS)
            audit_event = build_audit_event(
                event_type="knowledge.document_crawled" if error_reason is None else "knowledge.document_crawl_failed",
                project_id=project_id,
                actor_type="worker",
                actor_id=crawled_by,
                target_type="knowledge_document",
                target_id=document_id,
                before=before,
                after=after,
                input_refs={"source_url": [source_url], "knowledge_document_ids": [document_id]},
                output_refs={"knowledge_generation_job_ids": [job_id]},
                method_version="crawl4ai_adapter_v1",
                reason="crawl public URL for GEO knowledge source",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE project_id = %s AND target_type = %s AND target_id = %s
                ORDER BY created_at DESC
                LIMIT 5
                """,
                (_uuid(project_id), "knowledge_document", document_id),
            )
            audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        self.connection.commit()
        return RuntimeKnowledgeDocument(knowledge_document=after, audit_events=audit_events)

    def extract_runtime_knowledge_document_facts(
        self,
        extraction_input: RuntimeKnowledgeDocumentExtractionInput,
    ) -> RuntimeKnowledgeFactImportResult:
        project_id = extraction_input.project_id.strip()
        document_id = extraction_input.knowledge_document_id.strip()
        extracted_by = extraction_input.extracted_by.strip() or "runtime-console"
        if not project_id:
            raise ValueError("project_id is required")
        if not document_id:
            raise ValueError("knowledge_document_id is required")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(KNOWLEDGE_DOCUMENT_COLUMNS)}
                FROM knowledge_documents
                WHERE id = %s AND project_id = %s
                LIMIT 1
                """,
                (_uuid(document_id), _uuid(project_id)),
            )
            document_row = cursor.fetchone()
            if not document_row:
                raise ValueError("knowledge document not found")
            document = _row_dict(document_row, KNOWLEDGE_DOCUMENT_COLUMNS)
            cursor.execute(
                """
                SELECT id, market_code, target_brand, category
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            project_row = cursor.fetchone()
            if not project_row:
                raise ValueError("project not found")
            project = _row_dict(project_row, ("id", "market_code", "target_brand", "category"))
            cursor.execute(
                f"""
                SELECT {", ".join(KNOWLEDGE_DOCUMENT_VERSION_COLUMNS)}
                FROM knowledge_document_versions
                WHERE knowledge_document_id = %s
                ORDER BY version_number DESC
                LIMIT 1
                """,
                (_uuid(document_id),),
            )
            version_row = cursor.fetchone()
            if version_row:
                version = _row_dict(version_row, KNOWLEDGE_DOCUMENT_VERSION_COLUMNS)
                raw_text = str(version.get("raw_text") or "")
                version_id = str(version["id"])
            else:
                raw_text = str(document.get("raw_text") or "")
                version_id = stable_knowledge_id("knowledge-document-version-inline", document_id, document.get("content_hash") or "")
            if not raw_text.strip():
                raise ValueError("knowledge document has no raw_text")
            job_id = stable_knowledge_id("knowledge-extract-job", project_id, document_id, datetime.now(UTC).isoformat())
            cursor.execute(
                """
                INSERT INTO knowledge_generation_jobs (
                  id, project_id, job_type, status, request_payload, step_events, generation_model,
                  generation_prompt_version, secret_ref, requested_by, started_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                """,
                (
                    _uuid(job_id),
                    _uuid(project_id),
                    "extract_facts",
                    "running",
                    _json_payload({"knowledge_document_id": document_id, "max_facts": extraction_input.max_facts}),
                    _json_payload([{"step": "extract_started", "pipeline": KNOWLEDGE_APPLICATION_PIPELINE_VERSION}]),
                    extraction_input.model,
                    "knowledge_fact_extraction_v1",
                    extraction_input.secret_ref,
                    extracted_by,
                ),
            )
            model_facts: tuple[dict[str, Any], ...] | None = None
            model_step_events = [{"step": "extract_started", "pipeline": KNOWLEDGE_APPLICATION_PIPELINE_VERSION}]
            deepseek_key = self._knowledge_deepseek_api_key(extraction_input.secret_ref)
            if deepseek_key:
                try:
                    model_facts = deepseek_extract_knowledge_facts(
                        api_key=deepseek_key,
                        raw_text=raw_text,
                        target_brand=str(project.get("target_brand") or ""),
                        category=str(project.get("category") or ""),
                        market_code=str(project.get("market_code") or "AU"),
                        max_facts=extraction_input.max_facts,
                        model=extraction_input.model,
                    )
                    model_step_events.append(
                        {
                            "step": "deepseek_extract_succeeded",
                            "model": extraction_input.model,
                            "fact_count": len(model_facts),
                        }
                    )
                except ValueError as exc:
                    model_step_events.append(
                        {
                            "step": "deepseek_extract_fallback",
                            "model": extraction_input.model,
                            "error_reason": str(exc),
                        }
                    )
            else:
                model_step_events.append({"step": "deepseek_extract_skipped", "reason": "api_key_not_configured"})
            extraction = extract_knowledge_facts_from_document(
                project_id=project_id,
                document_id=document_id,
                document_version_id=version_id,
                raw_text=raw_text,
                source_url=str(document.get("source_url") or "") or None,
                market_code=str(project.get("market_code") or "AU"),
                target_brand=str(project.get("target_brand") or ""),
                category=str(project.get("category") or ""),
                extracted_by=extracted_by,
                max_facts=extraction_input.max_facts,
                auto_approve=extraction_input.auto_approve,
                model=extraction_input.model,
                model_facts=model_facts,
            )
            imported_rows: list[dict[str, Any]] = []
            for fact in extraction.facts:
                cursor.execute(
                    """
                    INSERT INTO localized_knowledge_facts (
                      id, project_id, market_code, fact_type, subject, predicate, object_value,
                      city, evidence_source_id, confidence, status, valid_from, valid_until,
                      knowledge_document_id, knowledge_document_version_id, source_url, source_quote,
                      source_kind, review_status, reviewed_by, reviewed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      object_value = EXCLUDED.object_value,
                      confidence = EXCLUDED.confidence,
                      status = EXCLUDED.status,
                      source_quote = EXCLUDED.source_quote,
                      review_status = EXCLUDED.review_status,
                      reviewed_by = EXCLUDED.reviewed_by,
                      reviewed_at = EXCLUDED.reviewed_at
                    """,
                    (
                        _uuid(fact.id),
                        _uuid(fact.project_id),
                        fact.market_code,
                        fact.fact_type,
                        fact.subject,
                        fact.predicate,
                        fact.object_value,
                        fact.city,
                        _uuid(fact.evidence_source_id),
                        fact.confidence,
                        fact.status,
                        _datetime(fact.valid_from),
                        _datetime(fact.valid_until),
                        _uuid(document_id),
                        _uuid(version_id),
                        document.get("source_url"),
                        fact.object_value[:500],
                        "model_extracted",
                        fact.status,
                        extracted_by if fact.status == KNOWLEDGE_FACT_APPROVED_STATUS else None,
                        datetime.now(UTC) if fact.status == KNOWLEDGE_FACT_APPROVED_STATUS else None,
                    ),
                )
                cursor.execute(
                    f"SELECT {', '.join(LOCALIZED_KNOWLEDGE_FACT_COLUMNS)} FROM localized_knowledge_facts WHERE id = %s",
                    (_uuid(fact.id),),
                )
                imported_rows.append(_row_dict(cursor.fetchone(), LOCALIZED_KNOWLEDGE_FACT_COLUMNS))
            embedding_audit = self._index_knowledge_fact_embeddings(
                cursor=cursor,
                facts=tuple(fact for fact in extraction.facts if fact.status == KNOWLEDGE_FACT_APPROVED_STATUS),
                actor_id=extracted_by,
            )
            cursor.execute(
                "UPDATE knowledge_documents SET status = %s, updated_at = now() WHERE id = %s AND project_id = %s",
                (DOCUMENT_STATUS_EXTRACTED, _uuid(document_id), _uuid(project_id)),
            )
            cursor.execute(
                """
                UPDATE knowledge_generation_jobs
                SET status = %s,
                    raw_output_hash = %s,
                    step_events = %s,
                    completed_at = now(),
                    updated_at = now()
                WHERE id = %s
                """,
                (
                    "succeeded",
                    extraction.raw_output_hash,
                    _json_payload(
                        [
                            *model_step_events,
                            {"step": "extract_succeeded", "knowledge_fact_count": len(extraction.facts)},
                        ]
                    ),
                    _uuid(job_id),
                ),
            )
            audit_events_to_save = tuple(event for event in (embedding_audit, extraction.audit_event) if event)
            self.save_audit_events(audit_events_to_save, cursor=cursor)
            after = {
                "project_id": project_id,
                "knowledge_document_id": document_id,
                "knowledge_fact_count": len(imported_rows),
                "knowledge_fact_ids": [str(row["id"]) for row in imported_rows],
                "generation_job_id": job_id,
            }
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE project_id = %s AND target_id IN (%s, %s)
                ORDER BY created_at DESC
                LIMIT 10
                """,
                (_uuid(project_id), document_id, project_id),
            )
            audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        self.connection.commit()
        return RuntimeKnowledgeFactImportResult(
            knowledge_fact_import=after,
            knowledge_facts=tuple(imported_rows),
            audit_events=audit_events,
        )

    def review_runtime_knowledge_fact(self, review: RuntimeKnowledgeFactReviewInput) -> dict[str, Any]:
        project_id = review.project_id.strip()
        fact_id = review.knowledge_fact_id.strip()
        reviewed_by = review.reviewed_by.strip() or "runtime-console"
        review_status = review.review_status.strip().lower()
        if review_status not in {"approved", "rejected", "archived", "pending_review"}:
            raise ValueError("knowledge fact review_status must be approved, rejected, archived, or pending_review")
        fact_status = KNOWLEDGE_FACT_APPROVED_STATUS if review_status == "approved" else review_status
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {', '.join(LOCALIZED_KNOWLEDGE_FACT_COLUMNS)} FROM localized_knowledge_facts WHERE id = %s AND project_id = %s FOR UPDATE",
                (_uuid(fact_id), _uuid(project_id)),
            )
            before_row = cursor.fetchone()
            if not before_row:
                raise ValueError("knowledge fact not found")
            before = _row_dict(before_row, LOCALIZED_KNOWLEDGE_FACT_COLUMNS)
            cursor.execute(
                """
                UPDATE localized_knowledge_facts
                SET status = %s,
                    review_status = %s,
                    reviewed_by = %s,
                    reviewed_at = now()
                WHERE id = %s AND project_id = %s
                """,
                (fact_status, review_status, reviewed_by, _uuid(fact_id), _uuid(project_id)),
            )
            cursor.execute(
                f"SELECT {', '.join(LOCALIZED_KNOWLEDGE_FACT_COLUMNS)} FROM localized_knowledge_facts WHERE id = %s AND project_id = %s",
                (_uuid(fact_id), _uuid(project_id)),
            )
            after = _row_dict(cursor.fetchone(), LOCALIZED_KNOWLEDGE_FACT_COLUMNS)
            audit_event = build_audit_event(
                event_type=f"knowledge.fact_{review_status}",
                project_id=project_id,
                actor_type="user",
                actor_id=reviewed_by,
                target_type="knowledge_fact",
                target_id=fact_id,
                before=before,
                after=after,
                input_refs={"knowledge_fact_ids": [fact_id], "decision": review.decision},
                output_refs={"knowledge_fact_ids": [fact_id], "review_status": review_status},
                method_version="knowledge_fact_review_v1",
                reason=review.notes or review.decision,
            )
            audit_events_to_save = (audit_event,)
            if review_status == "approved":
                fact_model = LocalizedKnowledgeFact(
                    id=str(after["id"]),
                    project_id=str(after["project_id"]),
                    market_code=str(after["market_code"]),
                    fact_type=str(after["fact_type"]),
                    subject=str(after["subject"]),
                    predicate=str(after["predicate"]),
                    object_value=str(after["object_value"]),
                    city=str(after["city"]) if after.get("city") else None,
                    evidence_source_id=str(after["evidence_source_id"]) if after.get("evidence_source_id") else None,
                    confidence=float(after["confidence"]),
                    status=str(after["status"]),
                    valid_from=after["valid_from"],
                    valid_until=after.get("valid_until"),
                )
                embedding_audit = self._index_knowledge_fact_embeddings(
                    cursor=cursor,
                    facts=(fact_model,),
                    actor_id=reviewed_by,
                )
                audit_events_to_save = tuple(event for event in (embedding_audit, audit_event) if event)
            self.save_audit_events(audit_events_to_save, cursor=cursor)
        self.connection.commit()
        return {"knowledge_fact": after, "audit_events": tuple(asdict(event) for event in audit_events_to_save)}

    def run_runtime_knowledge_application(
        self,
        request: RuntimeKnowledgeApplicationRequest,
    ) -> RuntimeKnowledgeApplicationResult:
        project_id = request.project_id.strip()
        requested_by = request.requested_by.strip() or "runtime-console"
        generation_type = request.generation_type.strip().lower()
        if generation_type not in {"content_draft", "faq_candidates", "prompt_candidates", "all"}:
            raise ValueError("generation_type must be content_draft, faq_candidates, prompt_candidates, or all")
        quantity = max(1, min(request.quantity, 50))
        job_id = stable_knowledge_id(
            "knowledge-application-job",
            project_id,
            generation_type,
            request.content_type,
            request.intent_type or "",
            request.city or "",
            datetime.now(UTC).isoformat(),
        )
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, market_code, target_brand, category
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            project_row = cursor.fetchone()
            if not project_row:
                raise ValueError("project not found")
            project = _row_dict(project_row, ("id", "market_code", "target_brand", "category"))
            cursor.execute(
                f"""
                SELECT {", ".join(LOCALIZED_KNOWLEDGE_FACT_COLUMNS)}
                FROM localized_knowledge_facts
                WHERE project_id = %s AND status = %s
                ORDER BY confidence DESC, fact_type ASC, id ASC
                LIMIT 50
                """,
                (_uuid(project_id), KNOWLEDGE_FACT_APPROVED_STATUS),
            )
            facts = tuple(_rows_dict(cursor.fetchall(), LOCALIZED_KNOWLEDGE_FACT_COLUMNS))
            cursor.execute(
                f"""
                SELECT {", ".join(PROMPT_QUESTION_READ_COLUMNS)}
                FROM prompt_questions
                WHERE project_id = %s AND status = %s
                ORDER BY priority ASC, id ASC
                LIMIT 200
                """,
                (_uuid(project_id), "active"),
            )
            prompts = tuple(_rows_dict(cursor.fetchall(), PROMPT_QUESTION_READ_COLUMNS))
            action = None
            if request.action_id:
                cursor.execute(
                    f"""
                    SELECT {", ".join(ACTION_RECOMMENDATION_COLUMNS)}
                    FROM action_recommendations
                    WHERE id = %s AND project_id = %s
                    LIMIT 1
                    """,
                    (_uuid(request.action_id), _uuid(project_id)),
                )
                action_row = cursor.fetchone()
                if action_row:
                    action = _row_dict(action_row, ACTION_RECOMMENDATION_COLUMNS)
            request_payload = {
                "generation_type": generation_type,
                "content_type": request.content_type,
                "target_platform": request.target_platform,
                "intent_type": request.intent_type,
                "city": request.city,
                "competitor": request.competitor,
                "quantity": quantity,
                "action_id": request.action_id,
                "prompt_ids": list(request.prompt_ids),
                "prompt_template_id": request.prompt_template_id,
                "prompt_template_version": request.prompt_template_version,
                "knowledge_source_policy": request.knowledge_source_policy,
            }
            cursor.execute(
                """
                INSERT INTO knowledge_generation_jobs (
                  id, project_id, job_type, status, request_payload, step_events,
                  generation_model, generation_prompt_version, secret_ref, requested_by, started_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                """,
                (
                    _uuid(job_id),
                    _uuid(project_id),
                    generation_type,
                    "running",
                    _json_payload(request_payload),
                    _json_payload([{"step": "generation_started", "pipeline": KNOWLEDGE_APPLICATION_PIPELINE_VERSION}]),
                    request.model,
                    KNOWLEDGE_APPLICATION_PIPELINE_VERSION,
                    request.secret_ref,
                    requested_by,
                ),
            )
            model_output: dict[str, Any] | None = None
            model_step_events = [{"step": "generation_started", "pipeline": KNOWLEDGE_APPLICATION_PIPELINE_VERSION}]
            deepseek_key = self._knowledge_deepseek_api_key(request.secret_ref)
            if deepseek_key:
                try:
                    model_output = deepseek_generate_knowledge_application(
                        api_key=deepseek_key,
                        target_brand=str(project["target_brand"]),
                        category=str(project["category"]),
                        market_code=str(project["market_code"] or "AU"),
                        facts=facts,
                        prompts=prompts,
                        generation_type=generation_type,
                        content_type=request.content_type.strip() or "faq",
                        target_platform=request.target_platform.strip() or "chatgpt",
                        intent_type=request.intent_type,
                        city=request.city,
                        competitor=request.competitor,
                        quantity=quantity,
                        model=request.model,
                    )
                    model_step_events.append(
                        {
                            "step": "deepseek_generation_succeeded",
                            "model": request.model,
                            "response_hash": model_output.get("response_hash"),
                        }
                    )
                except ValueError as exc:
                    model_step_events.append(
                        {
                            "step": "deepseek_generation_fallback",
                            "model": request.model,
                            "error_reason": str(exc),
                        }
                    )
            else:
                model_step_events.append({"step": "deepseek_generation_skipped", "reason": "api_key_not_configured"})
            artifacts = build_knowledge_application_artifacts(
                project_id=project_id,
                target_brand=str(project["target_brand"]),
                category=str(project["category"]),
                market_code=str(project["market_code"] or "AU"),
                facts=facts,
                prompts=prompts,
                action=action,
                generation_type=generation_type,
                content_type=request.content_type.strip() or "faq",
                target_platform=request.target_platform.strip() or "chatgpt",
                intent_type=request.intent_type,
                city=request.city,
                competitor=request.competitor,
                quantity=quantity,
                requested_by=requested_by,
                generation_job_id=job_id,
                model=request.model,
                model_output=model_output,
            )
            content_rows: list[dict[str, Any]] = []
            for draft in artifacts.content_drafts:
                cursor.execute(
                    """
                    INSERT INTO content_drafts (
                      id, project_id, title, content_type, content_template_id, target_question_ids,
                      target_city, target_platform, target_source_type, used_knowledge_fact_ids,
                      source_gap_types, source_action_id, evidence_answer_run_ids,
                      draft_markdown, review_status, created_by, created_at,
                      generation_job_id, source_document_ids, source_fact_ids,
                      generation_model, generation_prompt_version, raw_output_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(draft.id),
                        _uuid(draft.project_id),
                        draft.title,
                        draft.content_type,
                        draft.content_template_id,
                        _uuid_array(draft.target_question_ids),
                        draft.target_city,
                        draft.target_platform,
                        draft.target_source_type,
                        _uuid_array(draft.used_knowledge_fact_ids),
                        list(draft.source_gap_types),
                        _uuid(draft.source_action_id),
                        _uuid_array(draft.evidence_answer_run_ids),
                        draft.draft_markdown,
                        draft.review_status,
                        draft.created_by,
                        _datetime(draft.created_at),
                        _uuid(job_id),
                        [],
                        _uuid_array(draft.used_knowledge_fact_ids),
                        request.model,
                        GEO_CONTENT_DRAFT_PROMPT_VERSION,
                        artifacts.raw_output_hash,
                    ),
                )
                cursor.execute(
                    f"SELECT {', '.join(CONTENT_DRAFT_COLUMNS)} FROM content_drafts WHERE id = %s LIMIT 1",
                    (_uuid(draft.id),),
                )
                content_rows.append(_row_dict(cursor.fetchone(), CONTENT_DRAFT_COLUMNS))
            prompt_rows: list[dict[str, Any]] = []
            for candidate in artifacts.prompt_candidates:
                cursor.execute(
                    """
                    INSERT INTO prompt_candidates (
                      id, project_id, generation_job_id, text, intent_type, market_code, city,
                      language, target_brand, competitors, priority, intent_weight,
                      source_knowledge_fact_ids, rationale, duplicate_state, review_status,
                      generation_model, generation_prompt_version
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(str(candidate["id"])),
                        _uuid(project_id),
                        _uuid(job_id),
                        candidate["text"],
                        candidate["intent_type"],
                        candidate["market_code"],
                        candidate["city"],
                        candidate["language"],
                        candidate["target_brand"],
                        _json_payload(candidate["competitors"]),
                        candidate["priority"],
                        candidate["intent_weight"],
                        _uuid_array(candidate["source_knowledge_fact_ids"]),
                        candidate["rationale"],
                    candidate["duplicate_state"],
                    candidate["review_status"],
                    candidate["generation_model"],
                    request.prompt_template_version or candidate["generation_prompt_version"],
                ),
            )
                cursor.execute(
                    f"SELECT {', '.join(PROMPT_CANDIDATE_COLUMNS)} FROM prompt_candidates WHERE id = %s LIMIT 1",
                    (_uuid(str(candidate["id"])),),
                )
                prompt_rows.append(_row_dict(cursor.fetchone(), PROMPT_CANDIDATE_COLUMNS))
            faq_rows: list[dict[str, Any]] = []
            for candidate in artifacts.faq_candidates:
                cursor.execute(
                    """
                    INSERT INTO faq_answer_candidates (
                      id, project_id, generation_job_id, question, answer_markdown, target_prompt_ids,
                      used_knowledge_fact_ids, market_code, city, language, review_status,
                      generation_model, generation_prompt_version, rationale
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(str(candidate["id"])),
                        _uuid(project_id),
                        _uuid(job_id),
                        candidate["question"],
                        candidate["answer_markdown"],
                        _uuid_array(candidate["target_prompt_ids"]),
                        _uuid_array(candidate["used_knowledge_fact_ids"]),
                        candidate["market_code"],
                        candidate["city"],
                        candidate["language"],
                        candidate["review_status"],
                        candidate["generation_model"],
                        candidate["generation_prompt_version"],
                        candidate["rationale"],
                    ),
                )
                cursor.execute(
                    f"SELECT {', '.join(FAQ_ANSWER_CANDIDATE_COLUMNS)} FROM faq_answer_candidates WHERE id = %s LIMIT 1",
                    (_uuid(str(candidate["id"])),),
                )
                faq_rows.append(_row_dict(cursor.fetchone(), FAQ_ANSWER_CANDIDATE_COLUMNS))
            cursor.execute(
                """
                UPDATE knowledge_generation_jobs
                SET status = %s,
                    raw_output_hash = %s,
                    step_events = %s,
                    completed_at = now(),
                    updated_at = now()
                WHERE id = %s
                """,
                (
                    "succeeded",
                    artifacts.raw_output_hash,
                    _json_payload(
                        [
                            *model_step_events,
                            {
                                "step": "generation_succeeded",
                                "content_drafts": len(content_rows),
                                "prompt_candidates": len(prompt_rows),
                                "faq_candidates": len(faq_rows),
                            },
                        ]
                    ),
                    _uuid(job_id),
                ),
            )
            self.save_audit_events((artifacts.audit_event,), cursor=cursor)
            cursor.execute(
                f"SELECT {', '.join(KNOWLEDGE_GENERATION_JOB_COLUMNS)} FROM knowledge_generation_jobs WHERE id = %s LIMIT 1",
                (_uuid(job_id),),
            )
            job = _row_dict(cursor.fetchone(), KNOWLEDGE_GENERATION_JOB_COLUMNS)
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE project_id = %s AND target_type = %s AND target_id = %s
                ORDER BY created_at DESC
                LIMIT 5
                """,
                (_uuid(project_id), "knowledge_generation_job", job_id),
            )
            audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        self.connection.commit()
        return RuntimeKnowledgeApplicationResult(
            generation_job=job,
            content_drafts=tuple(content_rows),
            prompt_candidates=tuple(prompt_rows),
            faq_candidates=tuple(faq_rows),
            audit_events=audit_events,
        )

    def review_runtime_prompt_candidate(self, review: RuntimePromptCandidateReviewInput) -> dict[str, Any]:
        project_id = review.project_id.strip()
        candidate_id = review.prompt_candidate_id.strip()
        reviewed_by = review.reviewed_by.strip() or "runtime-console"
        review_status = review.review_status.strip().lower()
        if review_status not in {PROMPT_CANDIDATE_APPROVED, PROMPT_CANDIDATE_REJECTED, PROMPT_CANDIDATE_PENDING, PROMPT_CANDIDATE_ARCHIVED}:
            raise ValueError("prompt candidate review_status must be approved, rejected, pending_review, or archived")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {', '.join(PROMPT_CANDIDATE_COLUMNS)} FROM prompt_candidates WHERE id = %s AND project_id = %s FOR UPDATE",
                (_uuid(candidate_id), _uuid(project_id)),
            )
            before_row = cursor.fetchone()
            if not before_row:
                raise ValueError("prompt candidate not found")
            before = _row_dict(before_row, PROMPT_CANDIDATE_COLUMNS)
            cursor.execute(
                """
                UPDATE prompt_candidates
                SET review_status = %s, reviewed_by = %s, reviewed_at = now(), updated_at = now()
                WHERE id = %s AND project_id = %s
                """,
                (review_status, reviewed_by, _uuid(candidate_id), _uuid(project_id)),
            )
            cursor.execute(
                f"SELECT {', '.join(PROMPT_CANDIDATE_COLUMNS)} FROM prompt_candidates WHERE id = %s AND project_id = %s LIMIT 1",
                (_uuid(candidate_id), _uuid(project_id)),
            )
            after = _row_dict(cursor.fetchone(), PROMPT_CANDIDATE_COLUMNS)
            audit_event = build_audit_event(
                event_type=f"prompt_candidate_{review_status}",
                project_id=project_id,
                actor_type="user",
                actor_id=reviewed_by,
                target_type="prompt_candidate",
                target_id=candidate_id,
                before=before,
                after=after,
                input_refs={"prompt_candidate_ids": [candidate_id], "decision": review.decision},
                output_refs={"prompt_candidate_ids": [candidate_id], "review_status": review_status},
                method_version="prompt_candidate_review_v1",
                reason=review.notes or review.decision,
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        return {"prompt_candidate": after, "audit_events": (asdict(audit_event),)}

    def import_runtime_approved_prompt_candidates(
        self,
        prompt_import: RuntimePromptCandidateImportInput,
    ) -> RuntimePromptImportResult:
        project_id = prompt_import.project_id.strip()
        imported_by = prompt_import.imported_by.strip() or "runtime-console"
        if not project_id:
            raise ValueError("project_id is required")
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, market_code, industry_code, target_brand, prompt_version
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(project_id),),
            )
            project_row = cursor.fetchone()
            if not project_row:
                raise ValueError("project not found")
            project = _row_dict(project_row, ("id", "market_code", "industry_code", "target_brand", "prompt_version"))
            filters = ["project_id = %s", "review_status = %s"]
            params: list[object] = [_uuid(project_id), PROMPT_CANDIDATE_APPROVED]
            if prompt_import.prompt_candidate_ids:
                filters.append("id = ANY(%s)")
                params.append(_uuid_array(list(prompt_import.prompt_candidate_ids)))
            cursor.execute(
                f"""
                SELECT {", ".join(PROMPT_CANDIDATE_COLUMNS)}
                FROM prompt_candidates
                WHERE {" AND ".join(filters)}
                ORDER BY priority ASC, created_at ASC
                FOR UPDATE
                """,
                tuple(params),
            )
            candidates = _rows_dict(cursor.fetchall(), PROMPT_CANDIDATE_COLUMNS)
            if not candidates:
                raise ValueError("no approved prompt candidates found")
            prompt_version = (
                prompt_import.prompt_version
                or f"knowledge_generated_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
            )
            imported_rows: list[dict[str, Any]] = []
            prompt_ids: list[str] = []
            candidate_to_prompt: dict[str, str] = {}
            for index, candidate in enumerate(candidates, start=1):
                prompt_id = stable_knowledge_id("prompt-candidate-import", project_id, prompt_version, candidate["id"], candidate["text"])
                prompt_ids.append(prompt_id)
                candidate_to_prompt[str(candidate["id"])] = prompt_id
                cursor.execute(
                    """
                    INSERT INTO prompt_questions (
                      id, project_id, market_code, industry_code, text, intent_type, city,
                      language, target_brand, competitors, priority, intent_weight,
                      prompt_version, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      text = EXCLUDED.text,
                      intent_type = EXCLUDED.intent_type,
                      city = EXCLUDED.city,
                      language = EXCLUDED.language,
                      target_brand = EXCLUDED.target_brand,
                      competitors = EXCLUDED.competitors,
                      priority = EXCLUDED.priority,
                      intent_weight = EXCLUDED.intent_weight,
                      prompt_version = EXCLUDED.prompt_version,
                      status = EXCLUDED.status
                    """,
                    (
                        _uuid(prompt_id),
                        _uuid(project_id),
                        candidate["market_code"] or project["market_code"],
                        project["industry_code"],
                        candidate["text"],
                        candidate["intent_type"],
                        candidate["city"],
                        candidate["language"],
                        candidate["target_brand"] or project["target_brand"],
                        _json_payload(candidate["competitors"]),
                        int(candidate["priority"] or index),
                        float(candidate["intent_weight"] or 1.0),
                        prompt_version,
                        "active",
                    ),
                )
                cursor.execute(
                    """
                    UPDATE prompt_candidates
                    SET review_status = %s, imported_prompt_id = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (PROMPT_CANDIDATE_IMPORTED, _uuid(prompt_id), _uuid(str(candidate["id"]))),
                )
                cursor.execute(
                    f"SELECT {', '.join(PROMPT_QUESTION_READ_COLUMNS)} FROM prompt_questions WHERE id = %s LIMIT 1",
                    (_uuid(prompt_id),),
                )
                imported_rows.append(_row_dict(cursor.fetchone(), PROMPT_QUESTION_READ_COLUMNS))
            after = {
                "project_id": project_id,
                "prompt_count": len(imported_rows),
                "prompt_ids": prompt_ids,
                "prompt_version": prompt_version,
                "source_format": "prompt_candidates",
                "candidate_to_prompt": candidate_to_prompt,
            }
            audit_event = build_audit_event(
                event_type="prompt_candidate_imported",
                project_id=project_id,
                actor_type="user",
                actor_id=imported_by,
                target_type="prompt_import",
                target_id=stable_knowledge_id("prompt-candidate-import-audit", project_id, imported_by, prompt_version),
                before={"project_id": project_id, "imported_prompt_count": 0},
                after=after,
                input_refs={"prompt_candidate_ids": list(candidate_to_prompt.keys())},
                output_refs={"prompt_question_ids": prompt_ids},
                method_version="prompt_candidate_import_v1",
                reason="import approved knowledge-generated prompt candidates",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
            cursor.execute(
                f"""
                SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
                FROM audit_events
                WHERE project_id = %s AND target_type = %s AND target_id = %s
                ORDER BY created_at DESC
                LIMIT 5
                """,
                (_uuid(project_id), "prompt_import", audit_event.target_id),
            )
            audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        self.connection.commit()
        return RuntimePromptImportResult(prompt_import=after, prompts=tuple(imported_rows), audit_events=audit_events)

    def list_runtime_knowledge_application(
        self,
        *,
        project_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeKnowledgeApplicationPage:
        project_id = project_id.strip()
        if not project_id:
            raise ValueError("project_id is required")
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(KNOWLEDGE_DOCUMENT_COLUMNS)}
                FROM knowledge_documents
                WHERE project_id = %s
                ORDER BY updated_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (_uuid(project_id), limit, offset),
            )
            documents = tuple(_rows_dict(cursor.fetchall(), KNOWLEDGE_DOCUMENT_COLUMNS))
            cursor.execute(
                f"""
                SELECT {", ".join(LOCALIZED_KNOWLEDGE_FACT_COLUMNS)}
                FROM localized_knowledge_facts
                WHERE project_id = %s
                ORDER BY valid_from DESC, id DESC
                LIMIT %s
                """,
                (_uuid(project_id), 100),
            )
            facts = tuple(_rows_dict(cursor.fetchall(), LOCALIZED_KNOWLEDGE_FACT_COLUMNS))
            cursor.execute(
                f"""
                SELECT {", ".join(KNOWLEDGE_GENERATION_JOB_COLUMNS)}
                FROM knowledge_generation_jobs
                WHERE project_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (_uuid(project_id), 50),
            )
            jobs = tuple(_rows_dict(cursor.fetchall(), KNOWLEDGE_GENERATION_JOB_COLUMNS))
            cursor.execute(
                f"""
                SELECT {", ".join(PROMPT_CANDIDATE_COLUMNS)}
                FROM prompt_candidates
                WHERE project_id = %s
                ORDER BY created_at DESC, priority ASC
                LIMIT %s
                """,
                (_uuid(project_id), 100),
            )
            prompt_candidates = tuple(_rows_dict(cursor.fetchall(), PROMPT_CANDIDATE_COLUMNS))
            cursor.execute(
                f"""
                SELECT {", ".join(FAQ_ANSWER_CANDIDATE_COLUMNS)}
                FROM faq_answer_candidates
                WHERE project_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (_uuid(project_id), 100),
            )
            faq_candidates = tuple(_rows_dict(cursor.fetchall(), FAQ_ANSWER_CANDIDATE_COLUMNS))
            cursor.execute(
                f"""
                SELECT {", ".join(CONTENT_DRAFT_COLUMNS)}
                FROM content_drafts
                WHERE project_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (_uuid(project_id), 50),
            )
            content_drafts = tuple(
                self._load_runtime_content_draft(cursor=cursor, draft=draft)
                for draft in _rows_dict(cursor.fetchall(), CONTENT_DRAFT_COLUMNS)
            )
            cursor.execute("SELECT count(*) FROM knowledge_documents WHERE project_id = %s", (_uuid(project_id),))
            count_row = cursor.fetchone()
            total_count = int(count_row[0] if not isinstance(count_row, dict) else count_row["count"])
        return RuntimeKnowledgeApplicationPage(
            project_id=project_id,
            knowledge_documents=documents,
            knowledge_facts=facts,
            generation_jobs=jobs,
            prompt_candidates=prompt_candidates,
            faq_candidates=faq_candidates,
            content_drafts=content_drafts,
            total_count=total_count,
            limit=limit,
            offset=offset,
        )

    def _load_runtime_content_engine(
        self,
        *,
        cursor: DbCursor,
        project_id: str,
        review_status: str | None,
    ) -> RuntimeContentEngine:
        cursor.execute(
            f"""
            SELECT {", ".join(LOCALIZED_KNOWLEDGE_FACT_COLUMNS)}
            FROM localized_knowledge_facts
            WHERE project_id = %s AND status = %s
            ORDER BY market_code ASC, fact_type ASC, subject ASC, id ASC
            """,
            (_uuid(project_id), KNOWLEDGE_FACT_APPROVED_STATUS),
        )
        knowledge_facts = _rows_dict(cursor.fetchall(), LOCALIZED_KNOWLEDGE_FACT_COLUMNS)
        draft_filters = ["project_id = %s"]
        draft_params: list[object] = [_uuid(project_id)]
        if review_status:
            draft_filters.append("review_status = %s")
            draft_params.append(review_status)
        cursor.execute(
            f"""
            SELECT {", ".join(CONTENT_DRAFT_COLUMNS)}
            FROM content_drafts
            WHERE {" AND ".join(draft_filters)}
            ORDER BY created_at DESC, id DESC
            """,
            tuple(draft_params),
        )
        drafts = _rows_dict(cursor.fetchall(), CONTENT_DRAFT_COLUMNS)
        runtime_drafts = tuple(
            self._load_runtime_content_draft(cursor=cursor, draft=draft)
            for draft in drafts
        )
        cursor.execute(
            f"""
            SELECT {", ".join(INTEGRATION_CONNECTOR_COLUMNS)}
            FROM integration_connectors
            WHERE project_id = %s
            ORDER BY provider ASC
            """,
            (_uuid(project_id),),
        )
        connectors = _rows_dict(cursor.fetchall(), INTEGRATION_CONNECTOR_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(MANUAL_DISTRIBUTION_RECORD_COLUMNS)}
            FROM manual_distribution_records
            WHERE project_id = %s
            ORDER BY content_draft_id ASC, id ASC
            """,
            (_uuid(project_id),),
        )
        distribution_records = _rows_dict(cursor.fetchall(), MANUAL_DISTRIBUTION_RECORD_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE target_type = %s AND target_id = %s
            ORDER BY created_at ASC
            """,
            ("content_engine_fixture", project_id),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeContentEngine(
            project_id=project_id,
            knowledge_facts=knowledge_facts,
            content_drafts=runtime_drafts,
            integration_connectors=connectors,
            manual_distribution_records=distribution_records,
            audit_events=audit_events,
        )

    def _load_runtime_content_draft(self, *, cursor: DbCursor, draft: dict[str, Any]) -> RuntimeContentDraft:
        target_questions: list[dict[str, Any]] = []
        for prompt_id in tuple(str(value) for value in draft["target_question_ids"]):
            cursor.execute(
                f"""
                SELECT {", ".join(PROMPT_QUESTION_READ_COLUMNS)}
                FROM prompt_questions
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(prompt_id),),
            )
            prompt_row = cursor.fetchone()
            if prompt_row:
                target_questions.append(_row_dict(prompt_row, PROMPT_QUESTION_READ_COLUMNS))
        knowledge_facts: list[dict[str, Any]] = []
        for fact_id in tuple(str(value) for value in draft["used_knowledge_fact_ids"]):
            cursor.execute(
                f"""
                SELECT {", ".join(LOCALIZED_KNOWLEDGE_FACT_COLUMNS)}
                FROM localized_knowledge_facts
                WHERE id = %s AND status = %s
                LIMIT 1
                """,
                (_uuid(fact_id), KNOWLEDGE_FACT_APPROVED_STATUS),
            )
            fact_row = cursor.fetchone()
            if fact_row:
                knowledge_facts.append(_row_dict(fact_row, LOCALIZED_KNOWLEDGE_FACT_COLUMNS))
        answer_runs: list[dict[str, Any]] = []
        for answer_run_id in tuple(str(value) for value in draft["evidence_answer_run_ids"]):
            cursor.execute(
                f"""
                SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                       pq.text AS prompt_text,
                       pq.intent_type AS prompt_intent_type,
                       pq.priority AS prompt_priority,
                       pq.prompt_version AS prompt_version
                FROM answer_runs ar
                LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
                WHERE ar.id = %s
                LIMIT 1
                """,
                (_uuid(answer_run_id),),
            )
            answer_run_row = cursor.fetchone()
            if answer_run_row:
                answer_runs.append(_row_dict(answer_run_row, ANSWER_RUN_READ_COLUMNS))
        action_recommendation = None
        if draft["source_action_id"]:
            cursor.execute(
                f"""
                SELECT {", ".join(ACTION_RECOMMENDATION_COLUMNS)}
                FROM action_recommendations
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(str(draft["source_action_id"])),),
            )
            action_row = cursor.fetchone()
            if action_row:
                action_recommendation = _row_dict(action_row, ACTION_RECOMMENDATION_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(MANUAL_DISTRIBUTION_RECORD_COLUMNS)}
            FROM manual_distribution_records
            WHERE content_draft_id = %s
            ORDER BY id ASC
            """,
            (_uuid(str(draft["id"])),),
        )
        distribution_records = _rows_dict(cursor.fetchall(), MANUAL_DISTRIBUTION_RECORD_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (_uuid(str(draft["project_id"])), "content_draft", str(draft["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeContentDraft(
            draft=draft,
            target_questions=tuple(target_questions),
            knowledge_facts=tuple(knowledge_facts),
            answer_runs=tuple(answer_runs),
            action_recommendation=action_recommendation,
            manual_distribution_records=distribution_records,
            audit_events=audit_events,
        )

    def _load_runtime_report_export(
        self,
        *,
        cursor: DbCursor,
        report_export: dict[str, Any],
    ) -> RuntimeReportExport:
        score_snapshots: list[dict[str, Any]] = []
        for score_snapshot_id in tuple(str(value) for value in report_export["score_snapshot_ids"]):
            cursor.execute(
                f"""
                SELECT {", ".join(VISIBILITY_SCORE_SNAPSHOT_COLUMNS)}
                FROM visibility_score_snapshots
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(score_snapshot_id),),
            )
            snapshot_row = cursor.fetchone()
            if snapshot_row:
                score_snapshots.append(_row_dict(snapshot_row, VISIBILITY_SCORE_SNAPSHOT_COLUMNS))
        answer_runs: list[dict[str, Any]] = []
        for answer_run_id in tuple(str(value) for value in report_export["answer_run_ids"]):
            cursor.execute(
                f"""
                SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                       pq.text AS prompt_text,
                       pq.intent_type AS prompt_intent_type,
                       pq.priority AS prompt_priority,
                       pq.prompt_version AS prompt_version,
                       cc.total_cost AS total_cost,
                       citation_counts.citation_count AS citation_count,
                       audit_counts.audit_event_count AS audit_event_count
                FROM report_evidence re
                JOIN answer_runs ar ON ar.id = re.answer_run_id
                LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
                LEFT JOIN collection_costs cc ON cc.answer_run_id = ar.id
                LEFT JOIN (
                    SELECT answer_run_id, count(*) AS citation_count
                    FROM answer_citations
                    GROUP BY answer_run_id
                ) citation_counts ON citation_counts.answer_run_id = ar.id
                LEFT JOIN (
                    SELECT target_id AS answer_run_id, count(*) AS audit_event_count
                    FROM audit_events
                    WHERE target_type = 'answer_run'
                    GROUP BY target_id
                ) audit_counts ON audit_counts.answer_run_id = ar.id::text
                WHERE re.report_export_id = %s AND re.answer_run_id = %s
                ORDER BY re.created_at ASC
                LIMIT 1
                """,
                (_uuid(str(report_export["id"])), _uuid(answer_run_id)),
            )
            answer_run_row = cursor.fetchone()
            if answer_run_row:
                answer_runs.append(
                    _row_dict(
                        answer_run_row,
                        ANSWER_RUN_READ_COLUMNS + ("total_cost", "citation_count", "audit_event_count"),
                    )
                )
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE target_type = %s AND target_id = %s
            ORDER BY created_at ASC
            """,
            ("report_export", str(report_export["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        cursor.execute("SELECT count(*) FROM source_graphs WHERE project_id = %s", (_uuid(str(report_export["project_id"])),))
        graph_count_row = cursor.fetchone()
        graph_count = int(graph_count_row[0] if not isinstance(graph_count_row, dict) else graph_count_row["count"])
        citation_graph = (
            self._load_runtime_citation_graph(cursor=cursor, project_id=str(report_export["project_id"]))
            if graph_count > 0
            else None
        )
        return RuntimeReportExport(
            report_export=report_export,
            score_snapshots=tuple(score_snapshots),
            answer_runs=tuple(answer_runs),
            citation_graph=citation_graph,
            audit_events=audit_events,
        )

    def _load_runtime_citation_graph(self, *, cursor: DbCursor, project_id: str) -> RuntimeCitationGraph:
        cursor.execute(
            f"""
            SELECT {", ".join(SOURCE_GRAPH_COLUMNS)}
            FROM source_graphs
            WHERE project_id = %s
            ORDER BY citation_count DESC, source_domain ASC, source_type ASC
            """,
            (_uuid(project_id),),
        )
        nodes = _rows_dict(cursor.fetchall(), SOURCE_GRAPH_COLUMNS)
        runtime_nodes: list[RuntimeCitationGraphNode] = []
        for node in nodes:
            answer_run_ids = tuple(str(answer_run_id) for answer_run_id in node["answer_run_ids"])
            answer_runs: list[dict[str, Any]] = []
            for answer_run_id in answer_run_ids:
                cursor.execute(
                    f"""
                    SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                           pq.text AS prompt_text,
                           pq.intent_type AS prompt_intent_type,
                           pq.priority AS prompt_priority,
                           pq.prompt_version AS prompt_version
                    FROM answer_runs ar
                    LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
                    WHERE ar.id = %s
                    LIMIT 1
                    """,
                    (_uuid(answer_run_id),),
                )
                answer_run_row = cursor.fetchone()
                if answer_run_row:
                    answer_runs.append(_row_dict(answer_run_row, ANSWER_RUN_READ_COLUMNS))
            runtime_nodes.append(
                RuntimeCitationGraphNode(
                    node=node,
                    answer_runs=tuple(answer_runs),
                )
            )
        cursor.execute(
            """
            SELECT sge.id AS id,
                   sge.source_graph_id AS source_graph_id,
                   sge.answer_run_id AS answer_run_id,
                   sge.answer_citation_id AS answer_citation_id,
                   sge.relation_type AS relation_type,
                   sge.created_at AS created_at
            FROM source_graph_evidence sge
            JOIN source_graphs sg ON sg.id = sge.source_graph_id
            WHERE sg.project_id = %s
            ORDER BY sge.created_at ASC, sge.id ASC
            """,
            (_uuid(project_id),),
        )
        evidence_links = _rows_dict(cursor.fetchall(), SOURCE_GRAPH_EVIDENCE_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(SOURCE_GAP_COLUMNS)}
            FROM source_gaps
            WHERE project_id = %s
            ORDER BY expected_weight DESC, source_type ASC, gap_type ASC
            """,
            (_uuid(project_id),),
        )
        source_gaps = _rows_dict(cursor.fetchall(), SOURCE_GAP_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(COMPETITOR_BENCHMARK_COLUMNS)}
            FROM competitor_benchmarks
            WHERE project_id = %s
            ORDER BY competitor_name ASC
            """,
            (_uuid(project_id),),
        )
        competitor_benchmarks = _rows_dict(cursor.fetchall(), COMPETITOR_BENCHMARK_COLUMNS)
        return RuntimeCitationGraph(
            project_id=project_id,
            nodes=tuple(runtime_nodes),
            evidence_links=evidence_links,
            source_gaps=source_gaps,
            competitor_benchmarks=competitor_benchmarks,
        )

    def _load_runtime_score_snapshot(
        self,
        *,
        cursor: DbCursor,
        snapshot: dict[str, Any],
        snapshot_id: str,
    ) -> RuntimeScoreSnapshot:
        cursor.execute(
            f"""
            SELECT {", ".join(SCORE_CONTRIBUTION_COLUMNS)}
            FROM score_contributions
            WHERE score_snapshot_id = %s
            ORDER BY component_name ASC, created_at ASC
            """,
            (_uuid(snapshot_id),),
        )
        contributions = _rows_dict(cursor.fetchall(), SCORE_CONTRIBUTION_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                   pq.text AS prompt_text,
                   pq.intent_type AS prompt_intent_type,
                   pq.priority AS prompt_priority,
                   pq.prompt_version AS prompt_version
            FROM score_snapshot_runs ssr
            JOIN answer_runs ar ON ar.id = ssr.answer_run_id
            LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
            WHERE ssr.score_snapshot_id = %s
            GROUP BY {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                     pq.text, pq.intent_type, pq.priority, pq.prompt_version
            ORDER BY ar.collected_at ASC, ar.id ASC
            """,
            (_uuid(snapshot_id),),
        )
        answer_runs = _rows_dict(cursor.fetchall(), ANSWER_RUN_READ_COLUMNS)
        runtime_answer_runs: list[RuntimeScoreSnapshotRun] = []
        for answer_run in answer_runs:
            answer_run_id = str(answer_run["id"])
            cursor.execute(
                f"""
                SELECT {", ".join(ANSWER_ANALYSIS_READ_COLUMNS)}
                FROM answer_analyses
                WHERE answer_run_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (_uuid(answer_run_id),),
            )
            analysis_row = cursor.fetchone()
            runtime_answer_runs.append(
                RuntimeScoreSnapshotRun(
                    answer_run=answer_run,
                    analysis=_row_dict(analysis_row, ANSWER_ANALYSIS_READ_COLUMNS) if analysis_row else None,
                )
            )
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE target_type = %s AND target_id = %s
            ORDER BY created_at ASC
            """,
            ("visibility_score_snapshot", snapshot_id),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeScoreSnapshot(
            snapshot=snapshot,
            contributions=contributions,
            answer_runs=tuple(runtime_answer_runs),
            audit_events=audit_events,
        )

    def _load_runtime_evidence_run(
        self,
        *,
        cursor: DbCursor,
        answer_run: dict[str, Any],
        answer_run_id: str,
    ) -> RuntimeEvidenceRun:
        cursor.execute(
            f"""
            SELECT {", ".join(RAW_ANSWER_COLUMNS)}
            FROM raw_answers
            WHERE answer_run_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (_uuid(answer_run_id),),
        )
        raw_answer_row = cursor.fetchone()
        cursor.execute(
            f"""
            SELECT {", ".join(CITATION_COLUMNS)}
            FROM answer_citations
            WHERE answer_run_id = %s
            ORDER BY position ASC, created_at ASC
            """,
            (_uuid(answer_run_id),),
        )
        citations = _rows_dict(cursor.fetchall(), CITATION_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(ASSET_COLUMNS)}
            FROM evidence_assets
            WHERE answer_run_id = %s
            ORDER BY asset_type ASC, created_at ASC
            """,
            (_uuid(answer_run_id),),
        )
        assets = _rows_dict(cursor.fetchall(), ASSET_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(COLLECTOR_LOG_COLUMNS)}
            FROM collector_logs
            WHERE answer_run_id = %s
            ORDER BY created_at ASC
            """,
            (_uuid(answer_run_id),),
        )
        logs = _rows_dict(cursor.fetchall(), COLLECTOR_LOG_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(COLLECTION_COST_COLUMNS)}
            FROM collection_costs
            WHERE answer_run_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (_uuid(answer_run_id),),
        )
        cost_row = cursor.fetchone()
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE target_type = %s AND target_id = %s
            ORDER BY created_at ASC
            """,
            ("answer_run", answer_run_id),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeEvidenceRun(
            answer_run=answer_run,
            raw_answer=_row_dict(raw_answer_row, RAW_ANSWER_COLUMNS) if raw_answer_row else None,
            citations=citations,
            evidence_assets=assets,
            collector_logs=logs,
            collection_cost=_row_dict(cost_row, COLLECTION_COST_COLUMNS) if cost_row else None,
            audit_events=audit_events,
        )

    def save_project_bootstrap(self, bootstrap: ProjectBootstrap) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  set_config(%s, %s, false),
                  set_config(%s, %s, false)
                """,
                (
                    "app.rls_enabled",
                    "0",
                    "geno.runtime_project_access_control",
                    "0",
                ),
            )
            cursor.execute(
                """
                INSERT INTO market_profiles (id, market_code, payload)
                VALUES (%s, %s, %s)
                ON CONFLICT (market_code) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (
                    _uuid(_stable_id("market-profile", bootstrap.market_profile.market_code)),
                    bootstrap.market_profile.market_code,
                    _json_payload(bootstrap.market_profile),
                ),
            )
            cursor.execute(
                """
                INSERT INTO industry_profiles (id, market_code, industry_code, payload)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (
                    _uuid(
                        _stable_id(
                            "industry-profile",
                            bootstrap.industry_profile.market_code,
                            bootstrap.industry_profile.industry_code,
                        )
                    ),
                    bootstrap.industry_profile.market_code,
                    bootstrap.industry_profile.industry_code,
                    _json_payload(bootstrap.industry_profile),
                ),
            )
            cursor.execute(
                """
                INSERT INTO tenants (id, name, slug, created_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, slug = EXCLUDED.slug
                """,
                (
                    _uuid(bootstrap.tenant.id),
                    bootstrap.tenant.name,
                    bootstrap.tenant.slug,
                    _datetime(bootstrap.tenant.created_at),
                ),
            )
            cursor.execute(
                """
                INSERT INTO projects (
                  id, tenant_id, name, market_code, industry_code, target_brand, category,
                  prompt_version, status, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  name = EXCLUDED.name,
                  market_code = EXCLUDED.market_code,
                  industry_code = EXCLUDED.industry_code,
                  target_brand = EXCLUDED.target_brand,
                  category = EXCLUDED.category,
                  prompt_version = EXCLUDED.prompt_version,
                  status = EXCLUDED.status
                """,
                (
                    _uuid(bootstrap.project.id),
                    _uuid(bootstrap.project.tenant_id),
                    bootstrap.project.name,
                    bootstrap.project.market_code,
                    bootstrap.project.industry_code,
                    bootstrap.project.target_brand,
                    bootstrap.project.category,
                    bootstrap.project.prompt_version,
                    bootstrap.project.status,
                    _datetime(bootstrap.project.created_at),
                ),
            )
            for member in bootstrap.members:
                cursor.execute(
                    """
                    INSERT INTO project_members (id, project_id, user_id, role, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET role = EXCLUDED.role
                    """,
                    (
                        _uuid(member.id),
                        _uuid(member.project_id),
                        member.user_id,
                        member.role,
                        _datetime(member.created_at),
                    ),
                )
            cursor.execute(
                """
                INSERT INTO brand_entities (
                  id, project_id, canonical_name, official_domains, parent_company, product_lines, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  canonical_name = EXCLUDED.canonical_name,
                  official_domains = EXCLUDED.official_domains,
                  parent_company = EXCLUDED.parent_company,
                  product_lines = EXCLUDED.product_lines,
                  status = EXCLUDED.status
                """,
                (
                    _uuid(bootstrap.brand.id),
                    _uuid(bootstrap.brand.project_id),
                    bootstrap.brand.canonical_name,
                    _json_payload(bootstrap.brand.official_domains),
                    bootstrap.brand.parent_company,
                    _json_payload(bootstrap.brand.product_lines),
                    bootstrap.brand.status,
                ),
            )
            for competitor in bootstrap.competitors:
                cursor.execute(
                    """
                    INSERT INTO competitor_entities (
                      id, project_id, canonical_name, official_domains, parent_company, product_lines, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      canonical_name = EXCLUDED.canonical_name,
                      official_domains = EXCLUDED.official_domains,
                      parent_company = EXCLUDED.parent_company,
                      product_lines = EXCLUDED.product_lines,
                      status = EXCLUDED.status
                    """,
                    (
                        _uuid(competitor.id),
                        _uuid(competitor.project_id),
                        competitor.canonical_name,
                        _json_payload(competitor.official_domains),
                        competitor.parent_company,
                        _json_payload(competitor.product_lines),
                        competitor.status,
                    ),
                )
            for prompt in bootstrap.prompt_questions:
                cursor.execute(
                    """
                    INSERT INTO prompt_questions (
                      id, project_id, market_code, industry_code, text, intent_type, city,
                      language, target_brand, competitors, priority, intent_weight,
                      prompt_version, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      text = EXCLUDED.text,
                      intent_type = EXCLUDED.intent_type,
                      city = EXCLUDED.city,
                      language = EXCLUDED.language,
                      target_brand = EXCLUDED.target_brand,
                      competitors = EXCLUDED.competitors,
                      priority = EXCLUDED.priority,
                      intent_weight = EXCLUDED.intent_weight,
                      prompt_version = EXCLUDED.prompt_version,
                      status = EXCLUDED.status
                    """,
                    (
                        _uuid(prompt.id),
                        _uuid(prompt.project_id),
                        prompt.market_code,
                        prompt.industry_code,
                        prompt.text,
                        prompt.intent_type,
                        prompt.city,
                        prompt.language,
                        prompt.target_brand,
                        _json_payload(prompt.competitors),
                        prompt.priority,
                        prompt.intent_weight,
                        prompt.prompt_version,
                        prompt.status,
                    ),
            )
            self.save_audit_events(bootstrap.audit_events, cursor=cursor)
        self.connection.commit()

    def save_runtime_evidence_asset(self, asset: RuntimeEvidenceAssetInput) -> RuntimeEvidenceAsset:
        asset_id = _stable_id(
            "runtime-evidence-asset",
            asset.project_id,
            asset.answer_run_id or "",
            asset.asset_type,
            asset.url,
            asset.storage_key or "",
        )
        content_hash = _runtime_evidence_asset_content_hash(
            url=asset.url,
            content_hash=asset.content_hash,
            metadata=asset.metadata,
        )
        source_type = asset.source_type or ("answer_run" if asset.answer_run_id else None)
        source_id = asset.source_id or asset.answer_run_id
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO evidence_assets (
                  id, tenant_id, project_id, answer_run_id, asset_type, url, content_hash,
                  storage_backend, storage_key, bucket, content_type, byte_size,
                  metadata, visibility, created_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  content_hash = EXCLUDED.content_hash,
                  storage_backend = EXCLUDED.storage_backend,
                  storage_key = EXCLUDED.storage_key,
                  bucket = EXCLUDED.bucket,
                  content_type = EXCLUDED.content_type,
                  byte_size = EXCLUDED.byte_size,
                  metadata = EXCLUDED.metadata,
                  visibility = EXCLUDED.visibility,
                  updated_at = now()
                RETURNING {", ".join(ASSET_COLUMNS)}
                """,
                (
                    _uuid(asset_id),
                    _uuid(asset.tenant_id),
                    _uuid(asset.project_id),
                    _uuid(asset.answer_run_id),
                    asset.asset_type,
                    asset.url,
                    content_hash,
                    asset.storage_backend,
                    asset.storage_key,
                    asset.bucket,
                    asset.content_type,
                    asset.byte_size,
                    _json_payload(asset.metadata),
                    asset.visibility,
                    asset.created_by,
                ),
            )
            row = _row_dict(cursor.fetchone(), ASSET_COLUMNS)
            if source_type and source_id:
                cursor.execute(
                    """
                    INSERT INTO evidence_links (
                      id, project_id, source_type, source_id, target_type, target_id,
                      relation_type, answer_run_ids
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(_stable_id("evidence-link", asset.project_id, source_type, source_id, asset_id)),
                        _uuid(asset.project_id),
                        source_type,
                        _uuid(source_id),
                        "evidence_asset",
                        _uuid(asset_id),
                        asset.relation_type,
                        _uuid_array((asset.answer_run_id,) if asset.answer_run_id else ()),
                    ),
                )
            audit_event = build_audit_event(
                event_type="evidence.created",
                project_id=asset.project_id,
                actor_type="system",
                actor_id=asset.created_by,
                target_type="evidence_asset",
                target_id=asset_id,
                before=None,
                after={
                    "asset_id": asset_id,
                    "project_id": asset.project_id,
                    "answer_run_id": asset.answer_run_id,
                    "asset_type": asset.asset_type,
                    "content_hash": content_hash,
                    "content_type": asset.content_type,
                    "byte_size": asset.byte_size,
                    "visibility": asset.visibility,
                },
                input_refs={"answer_run_ids": [asset.answer_run_id] if asset.answer_run_id else []},
                output_refs={"evidence_asset_ids": [asset_id]},
                method_version="runtime_evidence_asset_v1",
                reason="persist runtime evidence asset metadata",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        return RuntimeEvidenceAsset(**row)

    def get_runtime_evidence_asset(self, *, evidence_asset_id: str) -> RuntimeEvidenceAsset | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(ASSET_COLUMNS)}
                FROM evidence_assets
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(evidence_asset_id),),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return RuntimeEvidenceAsset(**_row_dict(row, ASSET_COLUMNS))

    def save_raw_evidence_records(self, records: tuple[RawEvidenceRecord, ...]) -> None:
        with self.connection.cursor() as cursor:
            for record in records:
                cursor.execute(
                    """
                    INSERT INTO answer_runs (
                      id, project_id, prompt_question_id, platform, surface, access_method,
                      market_code, city, language, device, answer_present, surface_triggered,
                      sample_index, sample_size, model_or_surface, account_state,
                      collector_backend_id, collector_version, collected_at, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.answer_run.id),
                        _uuid(record.answer_run.project_id),
                        _uuid(record.answer_run.prompt_question_id),
                        record.answer_run.platform,
                        record.answer_run.surface,
                        record.answer_run.access_method,
                        record.answer_run.market_code,
                        record.answer_run.city,
                        record.answer_run.language,
                        record.answer_run.device,
                        record.answer_run.answer_present,
                        record.answer_run.surface_triggered,
                        record.answer_run.sample_index,
                        record.answer_run.sample_size,
                        record.answer_run.model_or_surface,
                        record.answer_run.account_state,
                        record.answer_run.collector_backend_id,
                        record.answer_run.collector_version,
                        _datetime(record.answer_run.collected_at),
                        record.answer_run.status,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO raw_answers (id, answer_run_id, answer_text, raw_payload, raw_payload_hash)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.raw_answer.id),
                        _uuid(record.raw_answer.answer_run_id),
                        record.raw_answer.answer_text,
                        _json_payload(record.raw_answer.raw_payload),
                        record.raw_answer.raw_payload_hash,
                    ),
                )
                for citation in record.citations:
                    cursor.execute(
                        """
                        INSERT INTO answer_citations (id, answer_run_id, url, domain, position, source_type)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            _uuid(citation.id),
                            _uuid(citation.answer_run_id),
                            citation.url,
                            citation.domain,
                            citation.position,
                            citation.source_type,
                        ),
                    )
                for asset in record.evidence_assets:
                    asset_content_hash = _runtime_evidence_asset_content_hash(
                        url=asset.url,
                        content_hash=asset.content_hash,
                        metadata={
                            "answer_run_id": record.answer_run.id,
                            "asset_type": asset.asset_type,
                        },
                    )
                    cursor.execute(
                        """
                        INSERT INTO evidence_assets (
                          id, tenant_id, project_id, answer_run_id, asset_type, url, content_hash,
                          storage_backend, storage_key, bucket, content_type, byte_size,
                          metadata, visibility, created_by
                        )
                        SELECT %s, p.tenant_id, ar.project_id, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, %s, %s
                        FROM answer_runs ar
                        JOIN projects p ON p.id = ar.project_id
                        WHERE ar.id = %s
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            _uuid(asset.id),
                            _uuid(asset.answer_run_id),
                            asset.asset_type,
                            asset.url,
                            asset_content_hash,
                            "external_url",
                            None,
                            None,
                            "image/png" if asset.asset_type == "screenshot" else "text/html"
                            if asset.asset_type == "html_snapshot"
                            else None,
                            None,
                            _json_payload(
                                {
                                    "source": "raw_evidence_record",
                                    "collector_backend_id": record.answer_run.collector_backend_id,
                                    "asset_type": asset.asset_type,
                                }
                            ),
                            "internal",
                            "collector",
                            _uuid(asset.answer_run_id),
                        ),
                    )
                    cursor.execute(
                        """
                        INSERT INTO evidence_links (
                          id, project_id, source_type, source_id, target_type, target_id,
                          relation_type, answer_run_ids
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            _uuid(_stable_id("evidence-link", record.answer_run.id, asset.id)),
                            _uuid(record.answer_run.project_id),
                            "answer_run",
                            _uuid(record.answer_run.id),
                            "evidence_asset",
                            _uuid(asset.id),
                            "contains_evidence_asset",
                            _uuid_array((record.answer_run.id,)),
                        ),
                    )
                for log in record.collector_logs:
                    cursor.execute(
                        """
                        INSERT INTO collector_logs (
                          id, answer_run_id, collector_backend_id, event_type, payload, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            _uuid(log.id),
                            _uuid(log.answer_run_id),
                            log.collector_backend_id,
                            log.event_type,
                            _json_payload(log.payload),
                            _datetime(log.created_at),
                        ),
                    )
                cursor.execute(
                    """
                    INSERT INTO collection_costs (
                      id, answer_run_id, project_id, collector_backend_id, llm_provider, llm_tokens,
                      llm_cost, proxy_or_vendor_cost, compute_cost, total_cost, duration_ms, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.collection_cost.id),
                        _uuid(record.collection_cost.answer_run_id),
                        _uuid(record.collection_cost.project_id),
                        record.collection_cost.collector_backend_id,
                        record.collection_cost.llm_provider,
                        record.collection_cost.llm_tokens,
                        record.collection_cost.llm_cost,
                        record.collection_cost.proxy_or_vendor_cost,
                        record.collection_cost.compute_cost,
                        record.collection_cost.total_cost,
                        record.collection_cost.duration_ms,
                        _datetime(record.collection_cost.created_at),
                    ),
                )
                self.save_audit_events(record.audit_events, cursor=cursor)
        self.connection.commit()

    def save_collection_failure_records(self, records: tuple[CollectionFailureRecord, ...]) -> None:
        with self.connection.cursor() as cursor:
            for record in records:
                cursor.execute(
                    """
                    INSERT INTO answer_runs (
                      id, project_id, prompt_question_id, platform, surface, access_method,
                      market_code, city, language, device, answer_present, surface_triggered,
                      sample_index, sample_size, model_or_surface, account_state,
                      collector_backend_id, collector_version, collected_at, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.answer_run.id),
                        _uuid(record.answer_run.project_id),
                        _uuid(record.answer_run.prompt_question_id),
                        record.answer_run.platform,
                        record.answer_run.surface,
                        record.answer_run.access_method,
                        record.answer_run.market_code,
                        record.answer_run.city,
                        record.answer_run.language,
                        record.answer_run.device,
                        record.answer_run.answer_present,
                        record.answer_run.surface_triggered,
                        record.answer_run.sample_index,
                        record.answer_run.sample_size,
                        record.answer_run.model_or_surface,
                        record.answer_run.account_state,
                        record.answer_run.collector_backend_id,
                        record.answer_run.collector_version,
                        _datetime(record.answer_run.collected_at),
                        record.answer_run.status,
                    ),
                )
                for log in record.collector_logs:
                    cursor.execute(
                        """
                        INSERT INTO collector_logs (
                          id, answer_run_id, collector_backend_id, event_type, payload, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            _uuid(log.id),
                            _uuid(log.answer_run_id),
                            log.collector_backend_id,
                            log.event_type,
                            _json_payload(log.payload),
                            _datetime(log.created_at),
                        ),
                    )
                cursor.execute(
                    """
                    INSERT INTO collection_costs (
                      id, answer_run_id, project_id, collector_backend_id, llm_provider, llm_tokens,
                      llm_cost, proxy_or_vendor_cost, compute_cost, total_cost, duration_ms, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.collection_cost.id),
                        _uuid(record.collection_cost.answer_run_id),
                        _uuid(record.collection_cost.project_id),
                        record.collection_cost.collector_backend_id,
                        record.collection_cost.llm_provider,
                        record.collection_cost.llm_tokens,
                        record.collection_cost.llm_cost,
                        record.collection_cost.proxy_or_vendor_cost,
                        record.collection_cost.compute_cost,
                        record.collection_cost.total_cost,
                        record.collection_cost.duration_ms,
                        _datetime(record.collection_cost.created_at),
                    ),
                )
                self.save_audit_events(record.audit_events, cursor=cursor)
        self.connection.commit()

    def save_collection_run_summary(self, summary: CollectionRunSummary, audit_event: AuditEvent) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO collection_run_summaries (
                  id, project_id, run_type, mode, planned_runs, attempted_runs, success_count,
                  failure_count, success_rate, trigger_rate, answer_present_rate, total_cost,
                  average_cost_per_run, total_duration_ms, average_duration_ms,
                  collector_backend_ids, platform_distribution,
                  city_distribution, access_method_distribution, failure_summary, answer_run_ids,
                  started_at, completed_at, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    _uuid(summary.id),
                    _uuid(summary.project_id),
                    summary.run_type,
                    summary.mode,
                    summary.planned_runs,
                    summary.attempted_runs,
                    summary.success_count,
                    summary.failure_count,
                    summary.success_rate,
                    summary.trigger_rate,
                    summary.answer_present_rate,
                    summary.total_cost,
                    summary.average_cost_per_run,
                    summary.total_duration_ms,
                    summary.average_duration_ms,
                    list(summary.collector_backend_ids),
                    _json_payload(summary.platform_distribution),
                    _json_payload(summary.city_distribution),
                    _json_payload(summary.access_method_distribution),
                    _json_payload(summary.failure_summary),
                    _uuid_array(summary.answer_run_ids),
                    _datetime(summary.started_at),
                    _datetime(summary.completed_at),
                    _datetime(summary.created_at),
                ),
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()

    def save_answer_analyses(self, analyses: tuple[AnswerAnalysis, ...]) -> None:
        with self.connection.cursor() as cursor:
            for analysis in analyses:
                cursor.execute(
                    """
                    INSERT INTO answer_analyses (
                      id, answer_run_id, parser_engine_id, analysis_version, payload, confidence
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      parser_engine_id = EXCLUDED.parser_engine_id,
                      analysis_version = EXCLUDED.analysis_version,
                      payload = EXCLUDED.payload,
                      confidence = EXCLUDED.confidence,
                      created_at = now()
                    """,
                    (
                        _uuid(analysis.id),
                        _uuid(analysis.answer_run_id),
                        analysis.parser_engine_id,
                        analysis.analysis_version,
                        _json_payload(analysis),
                        analysis.confidence,
                    ),
                )
                for call_log in _llm_call_logs_from_analysis(analysis):
                    cursor.execute(
                        """
                        INSERT INTO llm_call_logs (
                          id, project_id, answer_run_id, purpose, provider, model, prompt_version,
                          request_hash, response_hash, prompt_tokens, completion_tokens, total_tokens,
                          estimated_cost, latency_ms, status, error_message, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                          project_id = EXCLUDED.project_id,
                          answer_run_id = EXCLUDED.answer_run_id,
                          purpose = EXCLUDED.purpose,
                          provider = EXCLUDED.provider,
                          model = EXCLUDED.model,
                          prompt_version = EXCLUDED.prompt_version,
                          request_hash = EXCLUDED.request_hash,
                          response_hash = EXCLUDED.response_hash,
                          prompt_tokens = EXCLUDED.prompt_tokens,
                          completion_tokens = EXCLUDED.completion_tokens,
                          total_tokens = EXCLUDED.total_tokens,
                          estimated_cost = EXCLUDED.estimated_cost,
                          latency_ms = EXCLUDED.latency_ms,
                          status = EXCLUDED.status,
                          error_message = EXCLUDED.error_message,
                          created_at = EXCLUDED.created_at
                        """,
                        (
                            _uuid(str(call_log.get("id"))),
                            _uuid(str(call_log["project_id"])) if call_log.get("project_id") else None,
                            _uuid(str(call_log["answer_run_id"])) if call_log.get("answer_run_id") else None,
                            str(call_log.get("purpose") or "unknown"),
                            str(call_log.get("provider") or "unknown"),
                            str(call_log.get("model") or "unknown"),
                            str(call_log.get("prompt_version") or "unknown"),
                            str(call_log.get("request_hash") or ""),
                            str(call_log["response_hash"]) if call_log.get("response_hash") else None,
                            int(call_log.get("prompt_tokens") or 0),
                            int(call_log.get("completion_tokens") or 0),
                            int(call_log.get("total_tokens") or 0),
                            float(call_log.get("estimated_cost") or 0.0),
                            int(call_log.get("latency_ms") or 0),
                            str(call_log.get("status") or "unknown"),
                            str(call_log["error_message"]) if call_log.get("error_message") else None,
                            call_log.get("created_at"),
                        ),
                    )
        self.connection.commit()

    def save_score_snapshot(
        self,
        snapshot: VisibilityScoreSnapshot,
        contributions: tuple[ScoreContribution, ...],
        audit_event: AuditEvent,
    ) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO visibility_score_snapshots (
                  id, project_id, scope_type, scope_value, formula_version, platform_weights_snapshot,
                  final_score, trigger_rate, mention_rate, recommendation_rate, answer_run_ids,
                  created_at, dispersion, component_weights_snapshot
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    _uuid(snapshot.id),
                    _uuid(snapshot.project_id),
                    snapshot.scope_type,
                    snapshot.scope_value,
                    snapshot.formula_version,
                    _json_payload(snapshot.platform_weights_snapshot),
                    snapshot.final_score,
                    snapshot.trigger_rate,
                    snapshot.mention_rate,
                    snapshot.recommendation_rate,
                    _uuid_array(snapshot.answer_run_ids),
                    _datetime(snapshot.created_at),
                    snapshot.dispersion,
                    _json_payload(snapshot.component_weights_snapshot),
                ),
            )
            for contribution in contributions:
                cursor.execute(
                    """
                    INSERT INTO score_contributions (
                      id, score_snapshot_id, component_name, component_score, weight,
                      weighted_contribution, denominator, evidence_answer_run_ids,
                      positive_evidence_summary, negative_evidence_summary, confidence_note,
                      created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(contribution.id),
                        _uuid(contribution.score_snapshot_id),
                        contribution.component_name,
                        contribution.component_score,
                        contribution.weight,
                        contribution.weighted_contribution,
                        contribution.denominator,
                        _uuid_array(contribution.evidence_answer_run_ids),
                        contribution.positive_evidence_summary,
                        contribution.negative_evidence_summary,
                        contribution.confidence_note,
                        _datetime(contribution.created_at),
                    ),
                )
                for answer_run_id in contribution.evidence_answer_run_ids:
                    cursor.execute(
                        """
                        INSERT INTO score_snapshot_runs (id, score_snapshot_id, answer_run_id, contribution_role)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            _uuid(_stable_id("score-snapshot-run", snapshot.id, answer_run_id, contribution.component_name)),
                            _uuid(snapshot.id),
                            _uuid(answer_run_id),
                            contribution.component_name,
                        ),
                    )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()

    def save_citation_graph(self, project_id: str, graph: CitationGraphResult) -> None:
        with self.connection.cursor() as cursor:
            for node in graph.nodes:
                cursor.execute(
                    """
                    INSERT INTO source_graphs (
                      id, project_id, source_url, source_domain, source_type, topic,
                      source_gap_type, answer_run_ids, citation_count
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(node.id),
                        _uuid(node.project_id),
                        node.source_url,
                        node.source_domain,
                        node.source_type,
                        node.topic,
                        node.source_gap_type,
                        _uuid_array(node.answer_run_ids),
                        node.citation_count,
                    ),
                )
            for evidence in graph.evidence_links:
                cursor.execute(
                    """
                    INSERT INTO source_graph_evidence (
                      id, source_graph_id, answer_run_id, answer_citation_id, relation_type
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(evidence.id),
                        _uuid(evidence.source_graph_id),
                        _uuid(evidence.answer_run_id),
                        _uuid(evidence.answer_citation_id),
                        evidence.relation_type,
                    ),
                )
            for gap in graph.source_gaps:
                cursor.execute(
                    """
                    INSERT INTO source_gaps (
                      id, project_id, source_type, gap_type, observed_count,
                      expected_weight, recommendation
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (project_id, source_type, gap_type) DO UPDATE SET
                      observed_count = EXCLUDED.observed_count,
                      expected_weight = EXCLUDED.expected_weight,
                      recommendation = EXCLUDED.recommendation
                    """,
                    (
                        _uuid(_stable_id("source-gap", project_id, gap.source_type, gap.gap_type)),
                        _uuid(project_id),
                        gap.source_type,
                        gap.gap_type,
                        gap.observed_count,
                        gap.expected_weight,
                        gap.recommendation,
                    ),
                )
            for benchmark in graph.competitor_benchmarks:
                cursor.execute(
                    """
                    INSERT INTO competitor_benchmarks (
                      id, project_id, competitor_name, metric_scope, payload, answer_run_ids
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(benchmark.id),
                        _uuid(benchmark.project_id),
                        benchmark.competitor_name,
                        "project",
                        _json_payload(benchmark),
                        _uuid_array(benchmark.answer_run_ids),
                    ),
                )
        self.connection.commit()

    def save_report_export(self, report_export: ReportExport, audit_event: AuditEvent) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO report_exports (
                  id, project_id, market_code, report_version, report_type, score_snapshot_ids,
                  answer_run_ids, prompt_version, scoring_formula_version, platform_weights_snapshot,
                  method_disclosure, sample_size, window_start, window_end, methodology_hash, markdown_url, pdf_url,
                  csv_url, exported_by, exported_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    _uuid(report_export.id),
                    _uuid(report_export.project_id),
                    report_export.market_code,
                    report_export.report_version,
                    report_export.report_type,
                    _uuid_array(report_export.score_snapshot_ids),
                    _uuid_array(report_export.answer_run_ids),
                    report_export.prompt_version,
                    report_export.scoring_formula_version,
                    _json_payload(report_export.platform_weights_snapshot),
                    _json_payload(report_export.method_disclosure),
                    report_export.sample_size,
                    _datetime(report_export.window_start),
                    _datetime(report_export.window_end),
                    report_export.methodology_hash,
                    report_export.markdown_url,
                    report_export.pdf_url,
                    report_export.csv_url,
                    report_export.exported_by,
                    _datetime(report_export.exported_at),
                ),
            )
            for answer_run_id in report_export.answer_run_ids:
                cursor.execute(
                    """
                    INSERT INTO report_evidence (id, report_export_id, answer_run_id, evidence_role)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(_stable_id("report-evidence", report_export.id, answer_run_id, "raw_evidence")),
                        _uuid(report_export.id),
                        _uuid(answer_run_id),
                        "raw_evidence",
                    ),
                )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()

    def save_action_plan(
        self,
        *,
        actions: tuple[ActionRecommendation, ...],
        schedule: RetestSchedule,
        comparison: RetestComparison | None,
        audit_events: tuple[AuditEvent, ...],
    ) -> None:
        with self.connection.cursor() as cursor:
            for action in actions:
                cursor.execute(
                    """
                    INSERT INTO action_recommendations (
                      id, project_id, title, description, priority, status, owner_id,
                      source_gap_type, evidence_answer_run_ids, related_source_types,
                      next_check_date, created_at, action_type, customer_visible,
                      score_contribution_ids, visibility_note
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(action.id),
                        _uuid(action.project_id),
                        action.title,
                        action.description,
                        action.priority,
                        action.status,
                        action.owner_id,
                        action.source_gap_type,
                        _uuid_array(action.evidence_answer_run_ids),
                        list(action.related_source_types),
                        _datetime(action.next_check_date),
                        _datetime(action.created_at),
                        action.action_type,
                        action.customer_visible,
                        _uuid_array(action.score_contribution_ids),
                        action.visibility_note,
                    ),
                )
            cursor.execute(
                """
                INSERT INTO retest_schedules (
                  id, project_id, prompt_version, sample_size, offsets_days,
                  scheduled_dates, answer_run_ids, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    _uuid(schedule.id),
                    _uuid(schedule.project_id),
                    schedule.prompt_version,
                    schedule.sample_size,
                    list(schedule.offsets_days),
                    list(schedule.scheduled_dates),
                    _uuid_array(schedule.answer_run_ids),
                    _datetime(schedule.created_at),
                ),
            )
            if comparison:
                cursor.execute(
                    """
                    INSERT INTO retest_comparisons (
                      id, project_id, baseline_score, retest_score, score_delta,
                      baseline_answer_run_ids, retest_answer_run_ids, trend, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(comparison.id),
                        _uuid(comparison.project_id),
                        comparison.baseline_score,
                        comparison.retest_score,
                        comparison.score_delta,
                        _uuid_array(comparison.baseline_answer_run_ids),
                        _uuid_array(comparison.retest_answer_run_ids),
                        comparison.trend,
                        _datetime(comparison.created_at),
                    ),
                )
            self.save_audit_events(audit_events, cursor=cursor)
        self.connection.commit()

    def save_content_engine(
        self,
        *,
        facts: tuple[LocalizedKnowledgeFact, ...],
        drafts: tuple[ContentDraft, ...],
        connectors: tuple[IntegrationConnector, ...],
        distribution_records: tuple[ManualDistributionRecord, ...],
        audit_event: AuditEvent,
    ) -> None:
        with self.connection.cursor() as cursor:
            for fact in facts:
                cursor.execute(
                    """
                    INSERT INTO localized_knowledge_facts (
                      id, project_id, market_code, fact_type, subject, predicate, object_value,
                      city, evidence_source_id, confidence, status, valid_from, valid_until
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(fact.id),
                        _uuid(fact.project_id),
                        fact.market_code,
                        fact.fact_type,
                        fact.subject,
                        fact.predicate,
                        fact.object_value,
                        fact.city,
                        _uuid(fact.evidence_source_id),
                        fact.confidence,
                        fact.status,
                        _datetime(fact.valid_from),
                        _datetime(fact.valid_until),
                    ),
                )
            for draft in drafts:
                cursor.execute(
                    """
                    INSERT INTO content_drafts (
                      id, project_id, title, content_type, content_template_id, target_question_ids,
                      target_city, target_platform, target_source_type, used_knowledge_fact_ids,
                      source_gap_types, source_action_id, evidence_answer_run_ids,
                      draft_markdown, review_status, created_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(draft.id),
                        _uuid(draft.project_id),
                        draft.title,
                        draft.content_type,
                        draft.content_template_id,
                        _uuid_array(draft.target_question_ids),
                        draft.target_city,
                        draft.target_platform,
                        draft.target_source_type,
                        _uuid_array(draft.used_knowledge_fact_ids),
                        list(draft.source_gap_types),
                        _uuid(draft.source_action_id),
                        _uuid_array(draft.evidence_answer_run_ids),
                        draft.draft_markdown,
                        draft.review_status,
                        draft.created_by,
                        _datetime(draft.created_at),
                    ),
                )
            embedding_audit = self._index_knowledge_fact_embeddings(
                cursor=cursor,
                facts=facts,
                actor_id=audit_event.actor_id,
            )
            for connector in connectors:
                cursor.execute(
                    """
                    INSERT INTO integration_connectors (
                      id, project_id, provider, connection_status, capabilities, auth_mode, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(connector.id),
                        _uuid(connector.project_id),
                        connector.provider,
                        connector.connection_status,
                        list(connector.capabilities),
                        connector.auth_mode,
                        _datetime(connector.created_at),
                    ),
                )
            for record in distribution_records:
                cursor.execute(
                    """
                    INSERT INTO manual_distribution_records (
                      id, project_id, content_draft_id, platform, target_url, status,
                      submitted_at, checked_at, notes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.id),
                        _uuid(record.project_id),
                        _uuid(record.content_draft_id),
                        record.platform,
                        record.target_url,
                        record.status,
                        _datetime(record.submitted_at),
                        _datetime(record.checked_at),
                        record.notes,
                    ),
                )
            audit_events = (embedding_audit, audit_event) if embedding_audit else (audit_event,)
            self.save_audit_events(audit_events, cursor=cursor)
        self.connection.commit()

    def _index_knowledge_fact_embeddings(
        self,
        *,
        cursor: DbCursor,
        facts: tuple[LocalizedKnowledgeFact, ...],
        actor_id: str = "geno-core.knowledge",
        embedding_model: str = KNOWLEDGE_EMBEDDING_MODEL,
    ) -> AuditEvent | None:
        if not facts:
            return None
        indexed_ids: list[str] = []
        project_id = facts[0].project_id
        for fact in facts:
            fact_text = knowledge_fact_text(fact)
            embedding = embed_knowledge_text(fact_text)
            embedding_id = _stable_id("knowledge-fact-embedding", fact.id, embedding_model)
            cursor.execute(
                """
                INSERT INTO knowledge_fact_embeddings (
                  id, project_id, knowledge_fact_id, embedding_model, embedding, content_hash
                ) VALUES (%s, %s, %s, %s, %s::vector, %s)
                ON CONFLICT (knowledge_fact_id, embedding_model) DO UPDATE SET
                  embedding = EXCLUDED.embedding,
                  content_hash = EXCLUDED.content_hash,
                  updated_at = now()
                """,
                (
                    _uuid(embedding_id),
                    _uuid(fact.project_id),
                    _uuid(fact.id),
                    embedding_model,
                    _vector_literal(embedding),
                    knowledge_fact_content_hash(fact),
                ),
            )
            indexed_ids.append(embedding_id)
        return build_audit_event(
            event_type="knowledge_fact_embeddings_indexed",
            project_id=project_id,
            actor_type="system",
            actor_id=actor_id,
            target_type="knowledge_fact_embedding_index",
            target_id=project_id,
            before=None,
            after={
                "embedding_model": embedding_model,
                "knowledge_fact_count": len(facts),
                "knowledge_fact_ids": [fact.id for fact in facts],
                "embedding_ids": indexed_ids,
            },
            input_refs={"knowledge_fact_ids": [fact.id for fact in facts]},
            output_refs={"knowledge_fact_embedding_ids": indexed_ids},
            method_version="knowledge_fact_embedding_v1",
            reason="index localized knowledge facts into pgvector for runtime retrieval",
        )

    def save_traceability_bundle(self, bundle: TraceabilityBundle) -> None:
        with self.connection.cursor() as cursor:
            for link in bundle.evidence_links:
                cursor.execute(
                    """
                    INSERT INTO evidence_links (
                      id, project_id, source_type, source_id, target_type, target_id,
                      relation_type, answer_run_ids
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(link.id),
                        _uuid(link.project_id),
                        link.source_type,
                        _uuid(link.source_id),
                        link.target_type,
                        _uuid(link.target_id),
                        link.relation_type,
                        _uuid_array(link.answer_run_ids),
                    ),
                )
            cursor.execute(
                """
                INSERT INTO traceability_bundles (
                  id, project_id, subject_type, subject_id, report_export_ids,
                  score_snapshot_ids, score_contribution_ids, answer_run_ids, raw_answer_ids,
                  answer_citation_ids, evidence_asset_ids, source_graph_ids, source_gap_types,
                  action_recommendation_ids, content_draft_ids, audit_event_ids,
                  explanation_summary
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    _uuid(bundle.id),
                    _uuid(bundle.project_id),
                    bundle.subject_type,
                    _uuid(bundle.subject_id),
                    _uuid_array(bundle.report_export_ids),
                    _uuid_array(bundle.score_snapshot_ids),
                    _uuid_array(bundle.score_contribution_ids),
                    _uuid_array(bundle.answer_run_ids),
                    _uuid_array(bundle.raw_answer_ids),
                    _uuid_array(bundle.answer_citation_ids),
                    _uuid_array(bundle.evidence_asset_ids),
                    _uuid_array(bundle.source_graph_ids),
                    list(bundle.source_gap_types),
                    _uuid_array(bundle.action_recommendation_ids),
                    _uuid_array(bundle.content_draft_ids),
                    _uuid_array(bundle.audit_event_ids),
                    bundle.explanation_summary,
                ),
            )
        self.connection.commit()

    def save_audit_events(self, events: tuple[AuditEvent, ...], *, cursor: DbCursor | None = None) -> None:
        owns_cursor = cursor is None
        if cursor is None:
            cursor = self.connection.cursor().__enter__()
        try:
            for event in events:
                cursor.execute(
                    """
                    INSERT INTO audit_events (
                      id, event_type, project_id, actor_type, actor_id, target_type, target_id,
                      before_hash, after_hash, input_refs, output_refs, method_version, reason,
                      created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(event.id),
                        event.event_type,
                        _uuid(event.project_id),
                        event.actor_type,
                        event.actor_id,
                        event.target_type,
                        event.target_id,
                        event.before_hash,
                        event.after_hash,
                        _json_payload(event.input_refs),
                        _json_payload(event.output_refs),
                        event.method_version,
                        event.reason,
                        _datetime(event.created_at),
                    ),
                )
        finally:
            if owns_cursor:
                assert cursor is not None
                cursor.__exit__(None, None, None)
                self.connection.commit()
