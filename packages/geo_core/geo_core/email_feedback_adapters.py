from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from geo_core.email_delivery import runtime_email_body_hash
from geo_core.models import RuntimeNotificationEmailFeedbackInput


RUNTIME_NOTIFICATION_EMAIL_PROVIDER_FEEDBACK_ADAPTER_VERSION = (
    "runtime_notification_email_provider_feedback_adapter_v1"
)
SUPPORTED_RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_PROVIDERS = ("sendgrid", "mailgun", "postmark")

_SENDGRID_EVENT_MAP = {
    "bounce": "bounce",
    "dropped": "suppressed",
    "spamreport": "complaint",
    "unsubscribe": "unsubscribe",
    "group_unsubscribe": "unsubscribe",
}
_MAILGUN_EVENT_MAP = {
    "failed": "bounce",
    "rejected": "suppressed",
    "complained": "complaint",
    "unsubscribed": "unsubscribe",
}
_POSTMARK_RECORD_TYPE_MAP = {
    "bounce": "bounce",
    "spamcomplaint": "complaint",
    "subscriptionchange": "unsubscribe",
}
_DELIVERY_ID_KEYS = (
    "geo_delivery_id",
    "runtime_notification_delivery_id",
    "runtime_delivery_id",
    "delivery_id",
)


@dataclass(frozen=True)
class RuntimeNotificationEmailProviderFeedbackParseResult:
    provider: str
    adapter_version: str
    records: tuple[RuntimeNotificationEmailFeedbackInput, ...]
    ignored_event_count: int
    ignored_event_types: tuple[str, ...]
    payload_hash: str


def parse_runtime_notification_email_provider_feedback(
    *,
    provider: str,
    payload: Any,
    payload_hash: str | None = None,
    default_delivery_id: str | None = None,
) -> RuntimeNotificationEmailProviderFeedbackParseResult:
    normalized_provider = _normalize_provider(provider)
    normalized_payload_hash = payload_hash or _hash_json(payload)
    if normalized_provider == "sendgrid":
        records, ignored = _parse_sendgrid_events(
            payload,
            payload_hash=normalized_payload_hash,
            default_delivery_id=default_delivery_id,
        )
    elif normalized_provider == "mailgun":
        records, ignored = _parse_mailgun_events(
            payload,
            payload_hash=normalized_payload_hash,
            default_delivery_id=default_delivery_id,
        )
    elif normalized_provider == "postmark":
        records, ignored = _parse_postmark_events(
            payload,
            payload_hash=normalized_payload_hash,
            default_delivery_id=default_delivery_id,
        )
    else:
        supported = ", ".join(SUPPORTED_RUNTIME_NOTIFICATION_EMAIL_FEEDBACK_PROVIDERS)
        raise ValueError(f"unsupported runtime notification email feedback provider: {provider}; supported: {supported}")
    return RuntimeNotificationEmailProviderFeedbackParseResult(
        provider=normalized_provider,
        adapter_version=RUNTIME_NOTIFICATION_EMAIL_PROVIDER_FEEDBACK_ADAPTER_VERSION,
        records=tuple(records),
        ignored_event_count=len(ignored),
        ignored_event_types=tuple(ignored),
        payload_hash=normalized_payload_hash,
    )


def _normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower().replace("_", "-")
    aliases = {
        "twilio-sendgrid": "sendgrid",
        "twilio_sendgrid": "sendgrid",
        "postmarkapp": "postmark",
    }
    return aliases.get(normalized, normalized)


def _parse_sendgrid_events(
    payload: Any,
    *,
    payload_hash: str,
    default_delivery_id: str | None,
) -> tuple[list[RuntimeNotificationEmailFeedbackInput], list[str]]:
    events = payload if isinstance(payload, list) else [payload]
    records: list[RuntimeNotificationEmailFeedbackInput] = []
    ignored: list[str] = []
    for index, raw_event in enumerate(events):
        event = _as_dict(raw_event)
        event_type = _clean_text(event.get("event")).lower()
        feedback_type = _SENDGRID_EVENT_MAP.get(event_type)
        if not feedback_type:
            ignored.append(event_type or "unknown")
            continue
        delivery_id, delivery_id_source = _delivery_id_from_mapping(event, default_delivery_id=default_delivery_id)
        recipient = _clean_text(event.get("email")) or None
        provider_event_id = _first_clean_text(
            event.get("sg_event_id"),
            event.get("event_id"),
            event.get("sg_message_id"),
            event.get("smtp-id"),
        )
        if not delivery_id or not (recipient or provider_event_id):
            ignored.append(f"{event_type}:missing_required")
            continue
        records.append(
            RuntimeNotificationEmailFeedbackInput(
                delivery_id=delivery_id,
                feedback_type=feedback_type,
                recipient=recipient,
                provider="sendgrid",
                provider_event_id=provider_event_id or None,
                occurred_at=_parse_provider_datetime(event.get("timestamp")),
                metadata=_provider_metadata(
                    provider="sendgrid",
                    provider_event_type=event_type,
                    provider_event=event,
                    payload_hash=payload_hash,
                    index=index,
                    delivery_id_source=delivery_id_source,
                    recipient=recipient,
                    provider_event_id=provider_event_id,
                    schema="sendgrid_event_webhook_v1",
                ),
                recorded_by="email-provider-webhook",
                reason="record sendgrid runtime notification email feedback webhook",
            )
        )
    return records, ignored


def _parse_mailgun_events(
    payload: Any,
    *,
    payload_hash: str,
    default_delivery_id: str | None,
) -> tuple[list[RuntimeNotificationEmailFeedbackInput], list[str]]:
    raw_events = payload if isinstance(payload, list) else [payload]
    records: list[RuntimeNotificationEmailFeedbackInput] = []
    ignored: list[str] = []
    for index, raw_event in enumerate(raw_events):
        wrapper = _as_dict(raw_event)
        event = _as_dict(wrapper.get("event-data") if "event-data" in wrapper else wrapper)
        event_type = _clean_text(event.get("event")).lower()
        feedback_type = _MAILGUN_EVENT_MAP.get(event_type)
        if not feedback_type:
            ignored.append(event_type or "unknown")
            continue
        delivery_id, delivery_id_source = _delivery_id_from_mapping(
            event,
            default_delivery_id=default_delivery_id,
            nested_keys=("user-variables", "user_variables", "metadata"),
        )
        recipient = _clean_text(event.get("recipient")) or None
        message = _as_dict(event.get("message"))
        headers = _as_dict(message.get("headers"))
        provider_event_id = _first_clean_text(event.get("id"), message.get("id"), headers.get("message-id"))
        if not delivery_id or not (recipient or provider_event_id):
            ignored.append(f"{event_type}:missing_required")
            continue
        records.append(
            RuntimeNotificationEmailFeedbackInput(
                delivery_id=delivery_id,
                feedback_type=feedback_type,
                recipient=recipient,
                provider="mailgun",
                provider_event_id=provider_event_id or None,
                occurred_at=_parse_provider_datetime(event.get("timestamp")),
                metadata=_provider_metadata(
                    provider="mailgun",
                    provider_event_type=event_type,
                    provider_event=event,
                    payload_hash=payload_hash,
                    index=index,
                    delivery_id_source=delivery_id_source,
                    recipient=recipient,
                    provider_event_id=provider_event_id,
                    schema="mailgun_event_data_webhook_v1",
                    extras={"mailgun_severity": _clean_text(event.get("severity")) or None},
                ),
                recorded_by="email-provider-webhook",
                reason="record mailgun runtime notification email feedback webhook",
            )
        )
    return records, ignored


def _parse_postmark_events(
    payload: Any,
    *,
    payload_hash: str,
    default_delivery_id: str | None,
) -> tuple[list[RuntimeNotificationEmailFeedbackInput], list[str]]:
    raw_events = payload if isinstance(payload, list) else [payload]
    records: list[RuntimeNotificationEmailFeedbackInput] = []
    ignored: list[str] = []
    for index, raw_event in enumerate(raw_events):
        event = _as_dict(raw_event)
        record_type = _clean_text(event.get("RecordType") or event.get("record_type") or event.get("Type")).lower()
        feedback_type = _POSTMARK_RECORD_TYPE_MAP.get(record_type)
        if record_type == "subscriptionchange" and event.get("SuppressSending") is False:
            feedback_type = None
        if not feedback_type:
            ignored.append(record_type or "unknown")
            continue
        delivery_id, delivery_id_source = _delivery_id_from_mapping(
            event,
            default_delivery_id=default_delivery_id,
            nested_keys=("Metadata", "metadata"),
        )
        recipient = _clean_text(event.get("Email") or event.get("email")) or None
        provider_event_id = _first_clean_text(event.get("ID"), event.get("MessageID"), event.get("MessageId"))
        occurred_at = _parse_provider_datetime(
            event.get("BouncedAt")
            or event.get("ReceivedAt")
            or event.get("DeliveredAt")
            or event.get("ChangedAt")
        )
        if not delivery_id or not (recipient or provider_event_id):
            ignored.append(f"{record_type}:missing_required")
            continue
        records.append(
            RuntimeNotificationEmailFeedbackInput(
                delivery_id=delivery_id,
                feedback_type=feedback_type,
                recipient=recipient,
                provider="postmark",
                provider_event_id=provider_event_id or None,
                occurred_at=occurred_at,
                metadata=_provider_metadata(
                    provider="postmark",
                    provider_event_type=record_type,
                    provider_event=event,
                    payload_hash=payload_hash,
                    index=index,
                    delivery_id_source=delivery_id_source,
                    recipient=recipient,
                    provider_event_id=provider_event_id,
                    schema="postmark_webhook_v1",
                    extras={"postmark_bounce_type": _clean_text(event.get("Type")) or None},
                ),
                recorded_by="email-provider-webhook",
                reason="record postmark runtime notification email feedback webhook",
            )
        )
    return records, ignored


def _provider_metadata(
    *,
    provider: str,
    provider_event_type: str,
    provider_event: dict[str, Any],
    payload_hash: str,
    index: int,
    delivery_id_source: str,
    recipient: str | None,
    provider_event_id: str | None,
    schema: str,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source": "runtime_notification_email_provider_feedback_webhook",
        "adapter_version": RUNTIME_NOTIFICATION_EMAIL_PROVIDER_FEEDBACK_ADAPTER_VERSION,
        "provider": provider,
        "provider_event_schema": schema,
        "provider_event_type": provider_event_type,
        "provider_payload_sha256": payload_hash,
        "provider_payload_event_sha256": _hash_json(provider_event),
        "provider_payload_event_index": index,
        "provider_delivery_id_source": delivery_id_source,
    }
    if recipient:
        metadata["provider_recipient_hash"] = runtime_email_body_hash(_normalize_email_for_hash(recipient))
    if provider_event_id:
        metadata["provider_event_id_hash"] = runtime_email_body_hash(provider_event_id)
    for key, value in (extras or {}).items():
        if value is not None:
            metadata[key] = value
    return metadata


def _delivery_id_from_mapping(
    event: dict[str, Any],
    *,
    default_delivery_id: str | None,
    nested_keys: tuple[str, ...] = ("custom_args", "unique_args", "metadata"),
) -> tuple[str, str]:
    for key in _DELIVERY_ID_KEYS:
        value = _clean_text(event.get(key))
        if value:
            return value, key
    for nested_key in nested_keys:
        nested = _as_dict(event.get(nested_key))
        for key in _DELIVERY_ID_KEYS:
            value = _clean_text(nested.get(key))
            if value:
                return value, f"{nested_key}.{key}"
    value = _clean_text(default_delivery_id)
    return (value, "default_delivery_id") if value else ("", "missing")


def _parse_provider_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    text = _clean_text(value)
    if not text:
        return None
    try:
        if text.replace(".", "", 1).isdigit():
            return datetime.fromtimestamp(float(text), tz=UTC)
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_clean_text(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\r", "\n").split()).strip()


def _normalize_email_for_hash(value: str) -> str:
    return _clean_text(value).lower()


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
