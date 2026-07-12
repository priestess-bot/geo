from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from geno_core.models import ProjectBootstrap


TenantStatus = Literal["active", "disabled"]
ProjectStatus = Literal["active", "paused", "archived"]
ProjectMemberRole = Literal[
    "project_owner",
    "analyst",
    "reviewer",
    "knowledge_architect",
    "content_operator",
    "client_viewer",
]
MemberStatus = Literal["active", "disabled"]
AuditActorType = Literal["user", "system", "worker", "service"]

TENANT_STATUSES = frozenset(("active", "disabled"))
PROJECT_STATUSES = frozenset(("active", "paused", "archived"))
PROJECT_MEMBER_STATUSES = frozenset(("active", "disabled"))
PROJECT_MEMBER_ROLES = frozenset(
    (
        "project_owner",
        "analyst",
        "reviewer",
        "knowledge_architect",
        "content_operator",
        "client_viewer",
    )
)
LEGACY_PROJECT_ROLE_MAP: dict[str, ProjectMemberRole] = {
    "owner": "project_owner",
    "admin": "project_owner",
    "analyst": "analyst",
    "viewer": "client_viewer",
}
LEGACY_AUDIT_ACTOR_TYPE_MAP: dict[str, AuditActorType] = {
    "user": "user",
    "system": "system",
    "worker": "worker",
    "api": "service",
    "service": "service",
}
TENANT_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
BOOTSTRAP_AUDIT_EVENT_TYPE = "project_bootstrap_created"
BOOTSTRAP_AUDIT_OUTPUT_REF_KEYS = frozenset(
    ("competitor_entity_ids", "prompt_question_ids")
)
AUDIT_SENSITIVE_REF_KEY_PARTS = frozenset(
    (
        "authorization",
        "cookie",
        "credential",
        "password",
        "secret",
        "token",
    )
)


class SchemaV2TenancySeedValidationError(ValueError):
    """Raised before a malformed seed can reach the privileged repository."""

    def __init__(self, code: str, field: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.field = field
        self.detail = detail


@dataclass(frozen=True)
class CanonicalJsonObject:
    """Deeply immutable JSON object represented by canonical serialized bytes."""

    canonical_json: str

    def __post_init__(self) -> None:
        try:
            value = json.loads(self.canonical_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("canonical_json must contain valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("canonical_json must contain a JSON object")
        canonical = _canonical_json(value)
        if canonical != self.canonical_json:
            raise ValueError("canonical_json must use the canonical JSON representation")

    @classmethod
    def from_value(cls, value: object) -> CanonicalJsonObject:
        if is_dataclass(value) and not isinstance(value, type):
            value = asdict(value)
        try:
            canonical = _canonical_json(value)
            parsed = json.loads(canonical)
        except (TypeError, ValueError) as exc:
            raise ValueError("value must be JSON serializable") from exc
        if not isinstance(parsed, dict):
            raise ValueError("value must be a JSON object")
        return cls(canonical)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.canonical_json)


@dataclass(frozen=True)
class SchemaV2MarketProfileSeed:
    id: UUID
    market_code: str
    payload: CanonicalJsonObject


@dataclass(frozen=True)
class SchemaV2IndustryProfileSeed:
    id: UUID
    market_code: str
    industry_code: str
    payload: CanonicalJsonObject


@dataclass(frozen=True)
class SchemaV2TenantSeed:
    id: UUID
    name: str
    slug: str
    status: TenantStatus


@dataclass(frozen=True)
class SchemaV2ProjectSeed:
    id: UUID
    tenant_id: UUID
    name: str
    market_code: str
    industry_code: str
    target_brand: str
    category: str
    prompt_version: str
    status: ProjectStatus


@dataclass(frozen=True)
class SchemaV2ProjectMemberSeed:
    id: UUID
    tenant_id: UUID
    project_id: UUID
    user_id: str
    role: ProjectMemberRole
    status: MemberStatus
    invited_by: str | None


@dataclass(frozen=True)
class SchemaV2AuditEventSeed:
    id: UUID
    tenant_id: UUID
    project_id: UUID
    event_type: str
    actor_type: AuditActorType
    actor_id: str
    target_type: str
    target_id: str
    before_hash: str | None
    after_hash: str | None
    input_refs: CanonicalJsonObject
    output_refs: CanonicalJsonObject
    method_version: str | None
    reason: str | None


@dataclass(frozen=True)
class SchemaV2TenancySeed:
    market_profile: SchemaV2MarketProfileSeed
    industry_profile: SchemaV2IndustryProfileSeed
    tenant: SchemaV2TenantSeed
    project: SchemaV2ProjectSeed
    project_members: tuple[SchemaV2ProjectMemberSeed, ...]
    audit_events: tuple[SchemaV2AuditEventSeed, ...]


def translate_project_bootstrap_to_v2_seed(
    bootstrap: ProjectBootstrap,
    *,
    tenant_status: TenantStatus = "active",
    project_status: ProjectStatus | None = None,
) -> SchemaV2TenancySeed:
    """Translate the legacy bootstrap package into the sealed 0010 seed contract."""

    tenant_id = _uuid(bootstrap.tenant.id, "tenant.id")
    project_id = _uuid(bootstrap.project.id, "project.id")
    source_project_tenant_id = _uuid(bootstrap.project.tenant_id, "project.tenant_id")
    if source_project_tenant_id != tenant_id:
        _invalid("scope_mismatch", "project.tenant_id", "project tenant must match bootstrap tenant")
    market_code = _nonempty(bootstrap.market_profile.market_code, "market_profile.market_code")
    industry_market_code = _nonempty(
        bootstrap.industry_profile.market_code,
        "industry_profile.market_code",
    )
    industry_code = _nonempty(
        bootstrap.industry_profile.industry_code,
        "industry_profile.industry_code",
    )
    resolved_tenant_status = _status(tenant_status, TENANT_STATUSES, "tenant.status")
    resolved_project_status = _status(
        bootstrap.project.status if project_status is None else project_status,
        PROJECT_STATUSES,
        "project.status",
    )

    member_seeds: list[SchemaV2ProjectMemberSeed] = []
    for index, member in enumerate(bootstrap.members):
        prefix = f"project_members[{index}]"
        if _uuid(member.project_id, f"{prefix}.project_id") != project_id:
            _invalid("scope_mismatch", f"{prefix}.project_id", "member project must match bootstrap project")
        canonical_user_id = _canonical_user_id(member.user_id, f"{prefix}.user_id")
        member_seeds.append(
            SchemaV2ProjectMemberSeed(
                id=_stable_uuid("project-member", str(project_id), canonical_user_id),
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=canonical_user_id,
                role=_project_member_role(member.role, f"{prefix}.role"),
                status="active",
                invited_by=None,
            )
        )
    canonical_member_users = frozenset(member.user_id for member in member_seeds)
    audit_seeds: list[SchemaV2AuditEventSeed] = []
    for index, event in enumerate(bootstrap.audit_events):
        prefix = f"audit_events[{index}]"
        if _uuid(event.project_id, f"{prefix}.project_id") != project_id:
            _invalid("scope_mismatch", f"{prefix}.project_id", "audit project must match bootstrap project")
        event_type = _nonempty(event.event_type, f"{prefix}.event_type")
        actor_type = _audit_actor_type(event.actor_type, f"{prefix}.actor_type")
        actor_id = (
            _canonical_user_id(event.actor_id, f"{prefix}.actor_id")
            if actor_type == "user"
            else _nonempty(event.actor_id, f"{prefix}.actor_id")
        )
        if actor_type == "user" and actor_id not in canonical_member_users:
            _invalid(
                "audit_actor_not_member",
                f"{prefix}.actor_id",
                "user bootstrap audit actor must be a canonical project member",
            )
        input_refs = CanonicalJsonObject.from_value(event.input_refs)
        output_refs = CanonicalJsonObject.from_value(event.output_refs)
        _validate_bootstrap_audit_contract(
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            target_type=event.target_type,
            target_id=event.target_id,
            project_id=project_id,
            member_user_ids=canonical_member_users,
            input_refs=input_refs,
            output_refs=output_refs,
            prefix=prefix,
        )
        audit_seeds.append(
            SchemaV2AuditEventSeed(
                id=_uuid(event.id, f"{prefix}.id"),
                tenant_id=tenant_id,
                project_id=project_id,
                event_type=event_type,
                actor_type=actor_type,
                actor_id=actor_id,
                target_type=_nonempty(event.target_type, f"{prefix}.target_type"),
                target_id=_nonempty(event.target_id, f"{prefix}.target_id"),
                before_hash=event.before_hash,
                after_hash=event.after_hash,
                input_refs=input_refs,
                output_refs=output_refs,
                method_version=_optional_nonempty(event.method_version, f"{prefix}.method_version"),
                reason=_optional_trimmed(event.reason),
            )
        )

    seed = SchemaV2TenancySeed(
        market_profile=SchemaV2MarketProfileSeed(
            id=_stable_uuid("market-profile", market_code),
            market_code=market_code,
            payload=CanonicalJsonObject.from_value(bootstrap.market_profile),
        ),
        industry_profile=SchemaV2IndustryProfileSeed(
            id=_stable_uuid("industry-profile", industry_market_code, industry_code),
            market_code=industry_market_code,
            industry_code=industry_code,
            payload=CanonicalJsonObject.from_value(bootstrap.industry_profile),
        ),
        tenant=SchemaV2TenantSeed(
            id=tenant_id,
            name=_nonempty(bootstrap.tenant.name, "tenant.name"),
            slug=_tenant_slug(bootstrap.tenant.slug),
            status=resolved_tenant_status,
        ),
        project=SchemaV2ProjectSeed(
            id=project_id,
            tenant_id=tenant_id,
            name=_nonempty(bootstrap.project.name, "project.name"),
            market_code=_nonempty(bootstrap.project.market_code, "project.market_code"),
            industry_code=_nonempty(bootstrap.project.industry_code, "project.industry_code"),
            target_brand=_nonempty(bootstrap.project.target_brand, "project.target_brand"),
            category=_nonempty(bootstrap.project.category, "project.category"),
            prompt_version=_nonempty(
                bootstrap.project.prompt_version,
                "project.prompt_version",
            ),
            status=resolved_project_status,
        ),
        project_members=tuple(member_seeds),
        audit_events=tuple(audit_seeds),
    )
    validate_v2_tenancy_seed(seed)
    return seed


def validate_v2_tenancy_seed(seed: SchemaV2TenancySeed) -> None:
    """Fail closed on values or cross-scope references rejected by sealed 0010."""

    _require_exact_type(seed, SchemaV2TenancySeed, "seed")
    _require_exact_type(seed.market_profile, SchemaV2MarketProfileSeed, "market_profile")
    _require_exact_type(seed.industry_profile, SchemaV2IndustryProfileSeed, "industry_profile")
    _require_exact_type(seed.tenant, SchemaV2TenantSeed, "tenant")
    _require_exact_type(seed.project, SchemaV2ProjectSeed, "project")
    if type(seed.project_members) is not tuple:
        _invalid("invalid_dto_type", "project_members", "project_members must be a tuple")
    if type(seed.audit_events) is not tuple:
        _invalid("invalid_dto_type", "audit_events", "audit_events must be a tuple")
    for index, member in enumerate(seed.project_members):
        _require_exact_type(member, SchemaV2ProjectMemberSeed, f"project_members[{index}]")
    for index, event in enumerate(seed.audit_events):
        _require_exact_type(event, SchemaV2AuditEventSeed, f"audit_events[{index}]")

    _require_uuid(seed.market_profile.id, "market_profile.id")
    _canonical_text(seed.market_profile.market_code, "market_profile.market_code")
    _require_json_object(seed.market_profile.payload, "market_profile.payload")
    _require_uuid(seed.industry_profile.id, "industry_profile.id")
    _canonical_text(seed.industry_profile.market_code, "industry_profile.market_code")
    _canonical_text(seed.industry_profile.industry_code, "industry_profile.industry_code")
    _require_json_object(seed.industry_profile.payload, "industry_profile.payload")
    _require_uuid(seed.tenant.id, "tenant.id")
    _require_uuid(seed.project.id, "project.id")
    _require_uuid(seed.project.tenant_id, "project.tenant_id")
    _nonempty(seed.tenant.name, "tenant.name")
    if seed.tenant.slug != _tenant_slug(seed.tenant.slug):
        _invalid("noncanonical_value", "tenant.slug", "tenant.slug must be canonical")
    if seed.tenant.status != _status(seed.tenant.status, TENANT_STATUSES, "tenant.status"):
        _invalid("noncanonical_value", "tenant.status", "tenant.status must be canonical")
    _nonempty(seed.project.name, "project.name")
    _canonical_text(seed.project.market_code, "project.market_code")
    _canonical_text(seed.project.industry_code, "project.industry_code")
    _nonempty(seed.project.target_brand, "project.target_brand")
    _nonempty(seed.project.category, "project.category")
    _nonempty(seed.project.prompt_version, "project.prompt_version")
    if seed.project.status != _status(seed.project.status, PROJECT_STATUSES, "project.status"):
        _invalid("noncanonical_value", "project.status", "project.status must be canonical")

    if seed.industry_profile.market_code != seed.market_profile.market_code:
        _invalid("scope_mismatch", "industry_profile.market_code", "market codes must match")
    if seed.project.market_code != seed.market_profile.market_code:
        _invalid("scope_mismatch", "project.market_code", "market codes must match")
    if seed.project.industry_code != seed.industry_profile.industry_code:
        _invalid("scope_mismatch", "project.industry_code", "industry codes must match")
    if seed.project.tenant_id != seed.tenant.id:
        _invalid("scope_mismatch", "project.tenant_id", "project tenant must match seed tenant")
    if not seed.project_members:
        _invalid("missing_member", "project_members", "a tenancy seed requires a project member")
    if not seed.audit_events:
        _invalid("missing_audit", "audit_events", "a tenancy seed requires an immutable audit event")

    member_ids: set[UUID] = set()
    member_users: set[str] = set()
    active_owner_count = 0
    for index, member in enumerate(seed.project_members):
        prefix = f"project_members[{index}]"
        _require_uuid(member.id, f"{prefix}.id")
        if member.tenant_id != seed.tenant.id or member.project_id != seed.project.id:
            _invalid("scope_mismatch", prefix, "member scope must match seed project and tenant")
        if member.user_id != _canonical_user_id(member.user_id, f"{prefix}.user_id"):
            _invalid("noncanonical_value", f"{prefix}.user_id", "user_id must be canonical")
        expected_member_id = _stable_uuid("project-member", str(seed.project.id), member.user_id)
        if member.id != expected_member_id:
            _invalid(
                "noncanonical_member_id",
                f"{prefix}.id",
                "member id must be derived from project id and canonical user id",
            )
        if member.role != _status(member.role, PROJECT_MEMBER_ROLES, f"{prefix}.role"):
            _invalid("noncanonical_value", f"{prefix}.role", "member role must be canonical")
        if member.status != _status(member.status, PROJECT_MEMBER_STATUSES, f"{prefix}.status"):
            _invalid("noncanonical_value", f"{prefix}.status", "member status must be canonical")
        if member.invited_by is not None:
            _nonempty(member.invited_by, f"{prefix}.invited_by")
        if member.id in member_ids or member.user_id in member_users:
            _invalid("duplicate_member", prefix, "member ids and canonical user ids must be unique")
        member_ids.add(member.id)
        member_users.add(member.user_id)
        if member.role == "project_owner" and member.status == "active":
            active_owner_count += 1
    if active_owner_count == 0:
        _invalid(
            "missing_active_project_owner",
            "project_members",
            "a tenancy seed requires an active project_owner",
        )

    audit_ids: set[UUID] = set()
    for index, event in enumerate(seed.audit_events):
        prefix = f"audit_events[{index}]"
        _require_uuid(event.id, f"{prefix}.id")
        if event.tenant_id != seed.tenant.id or event.project_id != seed.project.id:
            _invalid("scope_mismatch", prefix, "audit scope must match seed project and tenant")
        event_type = _nonempty(event.event_type, f"{prefix}.event_type")
        if event.actor_type != _audit_actor_type(event.actor_type, f"{prefix}.actor_type"):
            _invalid("noncanonical_value", f"{prefix}.actor_type", "actor type must be canonical")
        actor_id = _nonempty(event.actor_id, f"{prefix}.actor_id")
        target_type = _nonempty(event.target_type, f"{prefix}.target_type")
        target_id = _nonempty(event.target_id, f"{prefix}.target_id")
        _sha256_or_none(event.before_hash, f"{prefix}.before_hash")
        _sha256_or_none(event.after_hash, f"{prefix}.after_hash")
        _require_json_object(event.input_refs, f"{prefix}.input_refs")
        _require_json_object(event.output_refs, f"{prefix}.output_refs")
        _optional_nonempty(event.method_version, f"{prefix}.method_version")
        _optional_text(event.reason, f"{prefix}.reason")
        _validate_bootstrap_audit_contract(
            event_type=event_type,
            actor_type=event.actor_type,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            project_id=seed.project.id,
            member_user_ids=frozenset(member_users),
            input_refs=event.input_refs,
            output_refs=event.output_refs,
            prefix=prefix,
        )
        if event.id in audit_ids:
            _invalid("duplicate_audit", f"{prefix}.id", "audit ids must be unique")
        audit_ids.add(event.id)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _stable_uuid(kind: str, *parts: str) -> UUID:
    return uuid5(NAMESPACE_URL, ":".join(("geno", kind, *parts)))


def _uuid(value: object, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise SchemaV2TenancySeedValidationError(
            "invalid_uuid",
            field,
            f"{field} must be a UUID",
        ) from exc


def _require_uuid(value: object, field: str) -> UUID:
    if not isinstance(value, UUID):
        _invalid("invalid_uuid", field, f"{field} must be a UUID")
    return value


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid("empty_value", field, f"{field} must be a non-empty string")
    return value.strip()


def _canonical_text(value: object, field: str) -> str:
    normalized = _nonempty(value, field)
    if value != normalized:
        _invalid("noncanonical_value", field, f"{field} must be trimmed")
    return normalized


def _optional_nonempty(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _nonempty(value, field)


def _optional_text(value: object, field: str) -> str | None:
    if value is not None and not isinstance(value, str):
        _invalid("invalid_text", field, f"{field} must be a string or null")
    return value


def _optional_trimmed(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("optional text value must be a string")
    return value.strip() or None


def _canonical_user_id(value: object, field: str) -> str:
    return _nonempty(value, field).lower()


def _require_json_object(value: object, field: str) -> CanonicalJsonObject:
    if type(value) is not CanonicalJsonObject:
        _invalid("invalid_json_object", field, f"{field} must be a CanonicalJsonObject")
    return value


def _require_exact_type(value: object, expected_type: type[object], field: str) -> None:
    if type(value) is not expected_type:
        _invalid(
            "invalid_dto_type",
            field,
            f"{field} must be an exact {expected_type.__name__} instance",
        )


def _tenant_slug(value: object) -> str:
    slug = _nonempty(value, "tenant.slug").lower()
    if not TENANT_SLUG_PATTERN.fullmatch(slug):
        _invalid("invalid_slug", "tenant.slug", "tenant.slug must be a canonical slug")
    return slug


def _status(value: object, allowed: frozenset[str], field: str) -> Any:
    normalized = _nonempty(value, field).lower()
    if normalized not in allowed:
        _invalid("unsupported_value", field, f"{field} is not supported by Schema v2")
    return normalized


def _project_member_role(value: object, field: str) -> ProjectMemberRole:
    normalized = _nonempty(value, field).lower()
    try:
        return LEGACY_PROJECT_ROLE_MAP[normalized]
    except KeyError as exc:
        raise SchemaV2TenancySeedValidationError(
            "unsupported_role",
            field,
            f"{field} is not mapped to a Schema v2 project role",
        ) from exc


def _audit_actor_type(value: object, field: str) -> AuditActorType:
    normalized = _nonempty(value, field).lower()
    try:
        return LEGACY_AUDIT_ACTOR_TYPE_MAP[normalized]
    except KeyError as exc:
        raise SchemaV2TenancySeedValidationError(
            "unsupported_actor_type",
            field,
            f"{field} is not supported by Schema v2",
        ) from exc


def _sha256_or_none(value: object, field: str) -> None:
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)):
        _invalid("invalid_sha256", field, f"{field} must be a lowercase SHA-256 hash")


def _invalid(code: str, field: str, detail: str) -> None:
    raise SchemaV2TenancySeedValidationError(code, field, detail)


def _validate_bootstrap_audit_contract(
    *,
    event_type: str,
    actor_type: str,
    actor_id: str,
    target_type: object,
    target_id: object,
    project_id: UUID,
    member_user_ids: frozenset[str],
    input_refs: CanonicalJsonObject,
    output_refs: CanonicalJsonObject,
    prefix: str,
) -> None:
    if event_type != BOOTSTRAP_AUDIT_EVENT_TYPE:
        _invalid(
            "unsupported_audit_event",
            f"{prefix}.event_type",
            "tenancy seeds only accept project_bootstrap_created audit events",
        )
    if target_type != "project" or target_id != str(project_id):
        _invalid(
            "audit_target_mismatch",
            f"{prefix}.target_id",
            "bootstrap audit target must be the exact seed project",
        )
    if actor_type == "user":
        canonical_actor_id = _canonical_user_id(actor_id, f"{prefix}.actor_id")
        if actor_id != canonical_actor_id or actor_id not in member_user_ids:
            _invalid(
                "audit_actor_not_member",
                f"{prefix}.actor_id",
                "user bootstrap audit actor must be a canonical project member",
            )

    input_value = input_refs.to_dict()
    output_value = output_refs.to_dict()
    _reject_sensitive_audit_ref_keys(input_value, f"{prefix}.input_refs")
    _reject_sensitive_audit_ref_keys(output_value, f"{prefix}.output_refs")
    if input_value:
        _invalid(
            "bootstrap_audit_input_refs_not_empty",
            f"{prefix}.input_refs",
            "bootstrap audit input_refs must be empty",
        )
    unsupported_keys = sorted(set(output_value) - BOOTSTRAP_AUDIT_OUTPUT_REF_KEYS)
    if unsupported_keys:
        _invalid(
            "unsupported_audit_ref",
            f"{prefix}.output_refs",
            "bootstrap audit output_refs contains unsupported keys",
        )
    for key, values in output_value.items():
        if type(values) is not list:
            _invalid(
                "invalid_audit_ref",
                f"{prefix}.output_refs.{key}",
                "bootstrap audit output refs must be UUID lists",
            )
        for value in values:
            field = f"{prefix}.output_refs.{key}"
            if not isinstance(value, str) or value != str(_uuid(value, field)):
                _invalid(
                    "invalid_uuid",
                    field,
                    "bootstrap audit output refs must use canonical UUID strings",
                )


def _reject_sensitive_audit_ref_keys(value: object, field: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = str(key).strip().lower().replace("-", "_")
            if any(part in normalized_key for part in AUDIT_SENSITIVE_REF_KEY_PARTS):
                _invalid(
                    "sensitive_audit_ref",
                    field,
                    "audit refs must not persist credential or session material",
                )
            _reject_sensitive_audit_ref_keys(nested, field)
    elif isinstance(value, list):
        for nested in value:
            _reject_sensitive_audit_ref_keys(nested, field)


__all__ = [
    "CanonicalJsonObject",
    "SchemaV2AuditEventSeed",
    "SchemaV2IndustryProfileSeed",
    "SchemaV2MarketProfileSeed",
    "SchemaV2ProjectMemberSeed",
    "SchemaV2ProjectSeed",
    "SchemaV2TenantSeed",
    "SchemaV2TenancySeed",
    "SchemaV2TenancySeedValidationError",
    "translate_project_bootstrap_to_v2_seed",
    "validate_v2_tenancy_seed",
]
