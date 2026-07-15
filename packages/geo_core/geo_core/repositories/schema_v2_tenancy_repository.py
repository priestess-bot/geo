from __future__ import annotations

import json
from typing import Any, Protocol

from geo_core.schema_v2.tenancy_seed import (
    CanonicalJsonObject,
    SchemaV2AuditEventSeed,
    SchemaV2ProjectMemberSeed,
    SchemaV2TenancySeed,
    validate_v2_tenancy_seed,
)


class SchemaV2SeedCursor(Protocol):
    def execute(self, sql: str, params: tuple[object, ...] = ()) -> Any: ...

    def fetchone(self) -> Any: ...

    def fetchall(self) -> Any: ...

    def __enter__(self) -> SchemaV2SeedCursor: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...


class SchemaV2PrivilegedConnection(Protocol):
    """Installer-owned, non-runtime connection with transaction control."""

    def cursor(self) -> SchemaV2SeedCursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class SchemaV2TenancySeedConflictError(RuntimeError):
    """An existing natural key has a different immutable seed payload."""

    def __init__(self, entity: str, identity: str) -> None:
        super().__init__(f"Schema v2 {entity} seed conflicts with existing row ({identity})")
        self.entity = entity
        self.identity = identity


class PrivilegedSchemaV2TenancyRepository:
    """Write sealed 0010 bootstrap rows using an installer/privileged connection.

    This adapter must never receive a runtime-owner connection. It deliberately
    performs no ``SET ROLE`` and sets no actor/project session GUCs.
    """

    def __init__(self, connection: SchemaV2PrivilegedConnection) -> None:
        if getattr(connection, "autocommit", False):
            raise ValueError("Schema v2 tenancy seeds require autocommit to be disabled")
        self.connection = connection

    def save(self, seed: SchemaV2TenancySeed) -> None:
        validate_v2_tenancy_seed(seed)
        try:
            with self.connection.cursor() as cursor:
                self._save_market(cursor, seed)
                self._save_industry(cursor, seed)
                self._save_tenant(cursor, seed)
                self._save_project(cursor, seed)
                for member in seed.project_members:
                    self._save_member(cursor, member)
                for event in seed.audit_events:
                    self._save_audit_event(cursor, event)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _save_market(self, cursor: SchemaV2SeedCursor, seed: SchemaV2TenancySeed) -> None:
        row = seed.market_profile
        expected = (row.id, row.market_code, row.payload)
        _insert_or_match(
            cursor,
            entity="market_profile",
            identity=f"market_code={row.market_code}",
            insert_sql="""
                INSERT INTO public.market_profiles (id, market_code, payload)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING 1
            """,
            insert_params=(row.id, row.market_code, _json_payload(row.payload)),
            select_sql="""
                SELECT id, market_code, payload
                FROM public.market_profiles
                WHERE id = %s OR market_code = %s
                ORDER BY id
            """,
            select_params=(row.id, row.market_code),
            expected=expected,
            json_indexes=(2,),
        )

    def _save_industry(self, cursor: SchemaV2SeedCursor, seed: SchemaV2TenancySeed) -> None:
        row = seed.industry_profile
        expected = (row.id, row.market_code, row.industry_code, row.payload)
        _insert_or_match(
            cursor,
            entity="industry_profile",
            identity=f"market_code={row.market_code},industry_code={row.industry_code}",
            insert_sql="""
                INSERT INTO public.industry_profiles (id, market_code, industry_code, payload)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING 1
            """,
            insert_params=(row.id, row.market_code, row.industry_code, _json_payload(row.payload)),
            select_sql="""
                SELECT id, market_code, industry_code, payload
                FROM public.industry_profiles
                WHERE id = %s OR (market_code = %s AND industry_code = %s)
                ORDER BY id
            """,
            select_params=(row.id, row.market_code, row.industry_code),
            expected=expected,
            json_indexes=(3,),
        )

    def _save_tenant(self, cursor: SchemaV2SeedCursor, seed: SchemaV2TenancySeed) -> None:
        row = seed.tenant
        expected = (row.id, row.name, row.slug, row.status)
        _insert_or_match(
            cursor,
            entity="tenant",
            identity=f"id={row.id}",
            insert_sql="""
                INSERT INTO public.tenants (id, name, slug, status)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING 1
            """,
            insert_params=expected,
            select_sql="""
                SELECT id, name, slug, status
                FROM public.tenants
                WHERE id = %s OR slug = %s
                ORDER BY id
            """,
            select_params=(row.id, row.slug),
            expected=expected,
        )

    def _save_project(self, cursor: SchemaV2SeedCursor, seed: SchemaV2TenancySeed) -> None:
        row = seed.project
        expected = (
            row.id,
            row.tenant_id,
            row.name,
            row.market_code,
            row.industry_code,
            row.target_brand,
            row.category,
            row.prompt_version,
            row.status,
        )
        _insert_or_match(
            cursor,
            entity="project",
            identity=f"id={row.id}",
            insert_sql="""
                INSERT INTO public.projects (
                    id, tenant_id, name, market_code, industry_code, target_brand,
                    category, prompt_version, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING 1
            """,
            insert_params=expected,
            select_sql="""
                SELECT id, tenant_id, name, market_code, industry_code, target_brand,
                       category, prompt_version, status
                FROM public.projects
                WHERE id = %s
            """,
            select_params=(row.id,),
            expected=expected,
        )

    def _save_member(
        self,
        cursor: SchemaV2SeedCursor,
        row: SchemaV2ProjectMemberSeed,
    ) -> None:
        expected = (
            row.id,
            row.tenant_id,
            row.project_id,
            row.user_id,
            row.role,
            row.status,
            row.invited_by,
        )
        _insert_or_match(
            cursor,
            entity="project_member",
            identity=f"project_id={row.project_id},user_id={row.user_id}",
            insert_sql="""
                INSERT INTO public.project_members (
                    id, tenant_id, project_id, user_id, role, status, invited_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING 1
            """,
            insert_params=expected,
            select_sql="""
                SELECT id, tenant_id, project_id, user_id, role, status, invited_by
                FROM public.project_members
                WHERE id = %s OR (project_id = %s AND user_id = %s)
                ORDER BY id
            """,
            select_params=(row.id, row.project_id, row.user_id),
            expected=expected,
        )

    def _save_audit_event(
        self,
        cursor: SchemaV2SeedCursor,
        row: SchemaV2AuditEventSeed,
    ) -> None:
        expected = (
            row.id,
            row.tenant_id,
            row.project_id,
            row.event_type,
            row.actor_type,
            row.actor_id,
            row.target_type,
            row.target_id,
            row.before_hash,
            row.after_hash,
            row.input_refs,
            row.output_refs,
            row.method_version,
            row.reason,
        )
        _insert_or_match(
            cursor,
            entity="audit_event",
            identity=f"id={row.id}",
            insert_sql="""
                INSERT INTO public.audit_events (
                    id, tenant_id, project_id, event_type, actor_type, actor_id,
                    target_type, target_id, before_hash, after_hash, input_refs,
                    output_refs, method_version, reason
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING 1
            """,
            insert_params=(
                *expected[:10],
                _json_payload(row.input_refs),
                _json_payload(row.output_refs),
                *expected[12:],
            ),
            select_sql="""
                SELECT id, tenant_id, project_id, event_type, actor_type, actor_id,
                       target_type, target_id, before_hash, after_hash, input_refs,
                       output_refs, method_version, reason
                FROM public.audit_events
                WHERE id = %s
            """,
            select_params=(row.id,),
            expected=expected,
            json_indexes=(10, 11),
        )


def _insert_or_match(
    cursor: SchemaV2SeedCursor,
    *,
    entity: str,
    identity: str,
    insert_sql: str,
    insert_params: tuple[object, ...],
    select_sql: str,
    select_params: tuple[object, ...],
    expected: tuple[object, ...],
    json_indexes: tuple[int, ...] = (),
) -> None:
    cursor.execute(insert_sql, insert_params)
    if cursor.fetchone() is not None:
        return
    cursor.execute(select_sql, select_params)
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise SchemaV2TenancySeedConflictError(entity, identity)
    actual = list(rows[0])
    if len(actual) != len(expected):
        raise SchemaV2TenancySeedConflictError(entity, identity)
    for index in json_indexes:
        actual[index] = _canonical_json_object(actual[index])
    if tuple(actual) != expected:
        raise SchemaV2TenancySeedConflictError(entity, identity)


def _canonical_json_object(value: object) -> CanonicalJsonObject:
    if isinstance(value, CanonicalJsonObject):
        return value
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("database returned invalid JSON") from exc
    return CanonicalJsonObject.from_value(value)


def _json_payload(value: CanonicalJsonObject) -> object:
    payload = value.to_dict()
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return payload
    return Jsonb(payload)


__all__ = [
    "PrivilegedSchemaV2TenancyRepository",
    "SchemaV2PrivilegedConnection",
    "SchemaV2TenancySeedConflictError",
]
