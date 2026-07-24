"""Pre-persistence governance for Workflow C manual UI evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
from html.parser import HTMLParser
import json
import re

from geo_core.sampling.contracts import SamplingRuleViolation


AUTOMATIC_POLICY_KEY = "manual-evidence-redaction-v1"
AUTOMATIC_POLICY_HASH = hashlib.sha256(
    b"workflow-c/manual-evidence-redaction-v1"
).hexdigest()
REDACTOR_VERSION_HASH = hashlib.sha256(
    b"workflow-c/manual-evidence-structured-redactor-v1"
).hexdigest()
SCANNER_VERSION_HASH = hashlib.sha256(
    b"workflow-c/manual-evidence-sensitive-scanner-v1"
).hexdigest()
CLASSIFICATION = "restricted_manual_evidence"
AUDIENCE = "admin_only"

_MAX_BYTES: Mapping[str, int] = {
    "screenshot": 10 * 1024 * 1024,
    "html_export": 10 * 1024 * 1024,
    "transcript_export": 5 * 1024 * 1024,
}
_ALLOWED_TYPES: Mapping[str, frozenset[str]] = {
    "screenshot": frozenset({"image/jpeg", "image/png", "image/webp"}),
    "html_export": frozenset({"text/html"}),
    "transcript_export": frozenset({"application/json", "text/plain"}),
}
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|authorization|cookie|credential|password|secret|session|token)",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])")
_AU_PHONE = re.compile(
    r"(?<!\d)(?:\+?61[\s().-]*[2-478]|0[2-478])(?:[\s().-]*\d){8}(?!\d)"
)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|authorization|cookie|password|secret|session|token)"
    r"\s*[:=]\s*(?!\[REDACTED_)([^\s,;]{4,})"
)
_URL_SECRET = re.compile(
    r"(?i)([?&](?:access_token|api_key|key|password|secret|session|token)=)"
    r"[^&#\s]+"
)


@dataclass(frozen=True, repr=False)
class GovernedManualArtifact:
    source_content_hash: str
    persisted_content_hash: str
    source_content_type: str
    persisted_content_type: str
    payload: bytearray = field(repr=False)
    governance_policy_hash: str
    redactor_version_hash: str
    scanner_version_hash: str
    pii_finding_count: int
    secret_finding_count: int
    redaction_assurance: str
    classification: str = CLASSIFICATION
    audience: str = AUDIENCE
    export_allowed: bool = False
    raw_retained: bool = False


class StrictManualArtifactGovernance:
    """Persist only a redacted derivative or an explicitly pre-redacted image."""

    def govern(
        self,
        *,
        evidence_kind: str,
        content_type: str,
        content: bytearray,
        governance_policy_key: str,
        pre_redacted_attestation: bool,
    ) -> GovernedManualArtifact:
        if governance_policy_key != AUTOMATIC_POLICY_KEY:
            raise SamplingRuleViolation(
                "manual evidence governance policy is not published"
            )
        normalized_type = content_type.strip().lower()
        allowed = _ALLOWED_TYPES.get(evidence_kind)
        if allowed is None or normalized_type not in allowed:
            raise SamplingRuleViolation(
                "manual evidence content type is not inspectable for its evidence kind"
            )
        if not content or len(content) > _MAX_BYTES[evidence_kind]:
            raise SamplingRuleViolation(
                "manual evidence artifact size is outside its limit"
            )
        if not _content_matches_type(content, normalized_type):
            raise SamplingRuleViolation(
                "manual evidence content does not match its declared type"
            )
        source_hash = hashlib.sha256(content).hexdigest()
        if evidence_kind == "screenshot":
            if not pre_redacted_attestation:
                raise SamplingRuleViolation(
                    "screenshots require an explicit pre-redacted content attestation"
                )
            payload = bytearray(content)
            pii_count = 0
            secret_count = 0
            assurance = "operator_attested_pre_redacted_pending_dual_review"
            persisted_type = normalized_type
        else:
            if pre_redacted_attestation:
                raise SamplingRuleViolation(
                    "pre-redacted attestation is only valid for screenshots"
                )
            value = _structured_value(content, normalized_type)
            redacted, pii_count, secret_count = _redact_value(value)
            payload = bytearray(_canonical_json(redacted))
            assurance = "automatic_structured_redaction"
            persisted_type = "application/vnd.geo.workflow-c-redacted+json"
        return GovernedManualArtifact(
            source_content_hash=source_hash,
            persisted_content_hash=hashlib.sha256(payload).hexdigest(),
            source_content_type=normalized_type,
            persisted_content_type=persisted_type,
            payload=payload,
            governance_policy_hash=AUTOMATIC_POLICY_HASH,
            redactor_version_hash=REDACTOR_VERSION_HASH,
            scanner_version_hash=SCANNER_VERSION_HASH,
            pii_finding_count=pii_count,
            secret_finding_count=secret_count,
            redaction_assurance=assurance,
        )


class _VisibleTextParser(HTMLParser):
    _HIDDEN = frozenset({"script", "style", "template", "noscript", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self.fragments: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in self._HIDDEN:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self._HIDDEN and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth and data.strip():
            self.fragments.append(data.strip())


def _structured_value(content: bytearray, content_type: str) -> object:
    try:
        text = bytes(content).decode("utf-8")
    except UnicodeDecodeError:
        raise SamplingRuleViolation("manual evidence text must be UTF-8") from None
    if content_type == "application/json":
        try:
            value = json.loads(text, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, SamplingRuleViolation):
            raise SamplingRuleViolation("manual evidence JSON is invalid") from None
        if not isinstance(value, (dict, list)):
            raise SamplingRuleViolation("manual evidence JSON must be an object or array")
        return {"schema_version": 1, "source_kind": "json", "content": value}
    if content_type == "text/html":
        parser = _VisibleTextParser()
        try:
            parser.feed(text)
            parser.close()
        except Exception:
            raise SamplingRuleViolation("manual evidence HTML cannot be parsed safely") from None
        visible = "\n".join(parser.fragments).strip()
        if not visible:
            raise SamplingRuleViolation("manual evidence HTML has no visible text")
        return {"schema_version": 1, "source_kind": "html", "text": visible}
    if content_type == "text/plain" and text.strip():
        return {"schema_version": 1, "source_kind": "text", "text": text.strip()}
    raise SamplingRuleViolation("manual evidence text is empty or unsupported")


def _redact_value(value: object, *, key: str | None = None) -> tuple[object, int, int]:
    if key is not None and _SENSITIVE_KEY.search(key):
        return "[REDACTED_SECRET]", 0, 1
    if isinstance(value, dict):
        result: dict[str, object] = {}
        pii = secret = 0
        for item_key, item in value.items():
            if not isinstance(item_key, str):
                raise SamplingRuleViolation("manual evidence JSON keys must be strings")
            redacted, item_pii, item_secret = _redact_value(item, key=item_key)
            result[item_key] = redacted
            pii += item_pii
            secret += item_secret
        return result, pii, secret
    if isinstance(value, list):
        result_list: list[object] = []
        pii = secret = 0
        for item in value:
            redacted, item_pii, item_secret = _redact_value(item)
            result_list.append(redacted)
            pii += item_pii
            secret += item_secret
        return result_list, pii, secret
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value, 0, 0
    raise SamplingRuleViolation("manual evidence contains unsupported structured content")


def _redact_text(value: str) -> tuple[str, int, int]:
    redacted, email_count = _EMAIL.subn("[REDACTED_EMAIL]", value)
    redacted, phone_count = _AU_PHONE.subn("[REDACTED_AU_PHONE]", redacted)
    redacted, bearer_count = _BEARER.subn("[REDACTED_SECRET]", redacted)
    redacted, assignment_count = _SECRET_ASSIGNMENT.subn(
        lambda match: f"{match.group(1)}=[REDACTED_SECRET]", redacted
    )
    redacted, url_count = _URL_SECRET.subn(
        lambda match: f"{match.group(1)}[REDACTED_SECRET]", redacted
    )
    return (
        redacted,
        email_count + phone_count,
        bearer_count + assignment_count + url_count,
    )


def _content_matches_type(content: bytearray, content_type: str) -> bool:
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/webp":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    try:
        text = bytes(content).decode("utf-8")
    except UnicodeDecodeError:
        return False
    if content_type == "text/html":
        return "<html" in text.casefold() or "<!doctype html" in text.casefold()
    return bool(text.strip())


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise SamplingRuleViolation(
            "manual evidence cannot be serialized canonically"
        ) from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SamplingRuleViolation("manual evidence JSON contains duplicate keys")
        result[key] = value
    return result


def wipe_bytearray(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


__all__ = [
    "AUDIENCE",
    "AUTOMATIC_POLICY_HASH",
    "AUTOMATIC_POLICY_KEY",
    "CLASSIFICATION",
    "GovernedManualArtifact",
    "REDACTOR_VERSION_HASH",
    "SCANNER_VERSION_HASH",
    "StrictManualArtifactGovernance",
    "wipe_bytearray",
]
