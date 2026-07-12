#!/usr/bin/env python3
"""Verify a Schema v2 domain contract against read-only PostgreSQL catalogs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT_ROOT = ROOT / "infra/db/schema-v2/parity"
REQUIRED_PG_ENVIRONMENT = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
EXPECTED_DATABASE_NAME = "geno_v2"
SAFE_TOKEN_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
QUALIFIED_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$")
CONSTRAINT_TYPES = {
    "primary_key": "p",
    "unique": "u",
    "foreign_key": "f",
    "composite_foreign_key": "f",
    "deferrable_composite_foreign_key": "f",
    "check": "c",
}
ROLE_ATTRIBUTES = (
    "login",
    "superuser",
    "create_database",
    "create_role",
    "replication",
    "bypass_rls",
)
TABLE_PRIVILEGES = (
    "DELETE",
    "INSERT",
    "REFERENCES",
    "SELECT",
    "TRIGGER",
    "TRUNCATE",
    "UPDATE",
)
POLICY_COMMANDS = {"all", "select", "insert", "update", "delete"}
TRIGGER_TIMINGS = {"before", "after", "instead_of"}
TRIGGER_EVENTS = {"insert", "update", "delete", "truncate"}
FUNCTION_KINDS = {"function", "procedure"}
FUNCTION_VOLATILITY = {"immutable", "stable", "volatile"}


class ParityVerifierError(RuntimeError):
    """Raised when a parity report cannot be produced safely."""


def _canonical_signature(value: str) -> str:
    return re.sub(r"\s*,\s*", ",", value.strip())


def _normalize_sql(value: object) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).strip().lower().split())


def _safe_string_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ParityVerifierError(f"{field} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise ParityVerifierError(f"{field} must not contain duplicates")
    return value


def _validate_expression_matcher(value: object, *, field: str, nullable: bool = True) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, dict) or not set(value).issubset({"exact", "required", "forbidden"}):
        raise ParityVerifierError(f"{field} must be null or an expression matcher")
    if "exact" in value and not isinstance(value["exact"], str):
        raise ParityVerifierError(f"{field}.exact must be a string")
    for key in ("required", "forbidden"):
        if key in value:
            _safe_string_list(value[key], field=f"{field}.{key}")


def load_contract(contract_root: Path, domain: str) -> dict[str, Any]:
    if not SAFE_TOKEN_RE.fullmatch(domain):
        raise ParityVerifierError("domain must contain only lowercase letters, digits, and underscores")
    contract_path = (contract_root / f"{domain}.json").resolve()
    try:
        contract_path.relative_to(contract_root.resolve())
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ParityVerifierError(f"cannot load parity contract for domain {domain!r}") from exc
    validate_contract(payload, domain=domain)
    return payload


def validate_contract(payload: object, *, domain: str) -> None:
    if not isinstance(payload, dict):
        raise ParityVerifierError("parity contract must be a JSON object")
    if payload.get("contract_version") != 2:
        raise ParityVerifierError("unsupported parity contract version")
    if payload.get("schema_generation") != 2:
        raise ParityVerifierError("parity contract schema_generation must be 2")
    if payload.get("domain") != domain:
        raise ParityVerifierError("parity contract domain does not match the requested domain")
    if payload.get("database_name") != EXPECTED_DATABASE_NAME:
        raise ParityVerifierError("parity contract database_name must remain geno_v2")
    if not isinstance(payload.get("source_parity"), dict):
        raise ParityVerifierError("source_parity mapping is required")
    if not isinstance(payload.get("v2_hardening"), dict):
        raise ParityVerifierError("v2_hardening deviations are required")
    connection_identity = payload.get("connection_identity")
    if not isinstance(connection_identity, dict):
        raise ParityVerifierError("connection_identity is required")
    _safe_string_list(
        connection_identity.get("must_not_equal_roles"),
        field="connection_identity.must_not_equal_roles",
    )

    roles = payload.get("roles")
    tables = payload.get("tables")
    functions = payload.get("functions")
    if not isinstance(roles, list) or not isinstance(tables, list) or not isinstance(functions, list):
        raise ParityVerifierError("roles, tables, and functions must be lists")

    seen_roles: set[str] = set()
    for role in roles:
        if not isinstance(role, dict) or not SAFE_TOKEN_RE.fullmatch(str(role.get("name", ""))):
            raise ParityVerifierError("role entries require a safe name")
        role_name = str(role["name"])
        if role_name in seen_roles:
            raise ParityVerifierError(f"duplicate role requirement: {role_name}")
        seen_roles.add(role_name)
        for attribute in ROLE_ATTRIBUTES:
            if not isinstance(role.get(attribute), bool):
                raise ParityVerifierError(f"role {role_name} requires boolean {attribute}")
        _safe_string_list(role.get("member_of"), field=f"role {role_name}.member_of")

    seen_tables: set[str] = set()
    for table in tables:
        if not isinstance(table, dict) or not QUALIFIED_NAME_RE.fullmatch(str(table.get("name", ""))):
            raise ParityVerifierError("table entries require a schema-qualified safe name")
        table_name = str(table["name"])
        if table_name in seen_tables:
            raise ParityVerifierError(f"duplicate table requirement: {table_name}")
        seen_tables.add(table_name)
        columns = table.get("columns")
        constraints = table.get("constraints")
        indexes = table.get("indexes", [])
        policies = table.get("policies", [])
        triggers = table.get("triggers", [])
        acl = table.get("acl")
        rls = table.get("rls")
        if not all(isinstance(value, list) for value in (columns, constraints, indexes, policies, triggers)):
            raise ParityVerifierError(f"table {table_name} structural requirements must be lists")
        if not isinstance(acl, dict):
            raise ParityVerifierError(f"table {table_name} requires an ACL contract")
        if not isinstance(rls, dict) or not all(
            isinstance(rls.get(key), bool) for key in ("enabled", "forced")
        ):
            raise ParityVerifierError(f"table {table_name} requires boolean RLS expectations")

        seen_columns: set[str] = set()
        for column in columns:
            if not isinstance(column, dict) or not SAFE_TOKEN_RE.fullmatch(str(column.get("name", ""))):
                raise ParityVerifierError(f"table {table_name} has an invalid column")
            column_name = str(column["name"])
            if column_name in seen_columns:
                raise ParityVerifierError(f"table {table_name} repeats column {column_name}")
            seen_columns.add(column_name)
            if not isinstance(column.get("type"), str) or not isinstance(column.get("not_null"), bool):
                raise ParityVerifierError(f"column {table_name}.{column_name} lacks type/not_null")
            if "default" not in column or (
                column["default"] is not None and not isinstance(column["default"], str)
            ):
                raise ParityVerifierError(f"column {table_name}.{column_name} requires a default contract")

        seen_constraints: set[str] = set()
        for constraint in constraints:
            if not isinstance(constraint, dict):
                raise ParityVerifierError(f"table {table_name} has an invalid constraint")
            name = str(constraint.get("name", ""))
            category = constraint.get("category")
            if not SAFE_TOKEN_RE.fullmatch(name) or category not in CONSTRAINT_TYPES:
                raise ParityVerifierError(f"table {table_name} has an invalid constraint requirement")
            if name in seen_constraints:
                raise ParityVerifierError(f"table {table_name} repeats constraint {name}")
            seen_constraints.add(name)
            if not isinstance(constraint.get("validated"), bool):
                raise ParityVerifierError(f"constraint {table_name}.{name} requires validated")
            if category == "check":
                _validate_expression_matcher(
                    constraint.get("expression"),
                    field=f"constraint {table_name}.{name}.expression",
                    nullable=False,
                )

        for index in indexes:
            if not isinstance(index, dict) or not SAFE_TOKEN_RE.fullmatch(str(index.get("name", ""))):
                raise ParityVerifierError(f"table {table_name} has an invalid index")
            if not all(isinstance(index.get(key), bool) for key in ("unique", "valid", "ready")):
                raise ParityVerifierError(f"table {table_name} index flags must be boolean")
            _safe_string_list(index.get("keys"), field=f"index {index['name']}.keys")
            _validate_expression_matcher(index.get("predicate"), field=f"index {index['name']}.predicate")

        for policy in policies:
            if not isinstance(policy, dict) or not SAFE_TOKEN_RE.fullmatch(str(policy.get("name", ""))):
                raise ParityVerifierError(f"table {table_name} has an invalid policy")
            if policy.get("command") not in POLICY_COMMANDS or not isinstance(policy.get("permissive"), bool):
                raise ParityVerifierError(f"policy {policy.get('name')} has invalid command/mode")
            _safe_string_list(policy.get("roles"), field=f"policy {policy['name']}.roles")
            _validate_expression_matcher(policy.get("using"), field=f"policy {policy['name']}.using")
            _validate_expression_matcher(
                policy.get("with_check"), field=f"policy {policy['name']}.with_check"
            )

        for trigger in triggers:
            if not isinstance(trigger, dict) or not SAFE_TOKEN_RE.fullmatch(str(trigger.get("name", ""))):
                raise ParityVerifierError(f"table {table_name} has an invalid trigger")
            if trigger.get("timing") not in TRIGGER_TIMINGS:
                raise ParityVerifierError(f"trigger {trigger.get('name')} has invalid timing")
            events = _safe_string_list(trigger.get("events"), field=f"trigger {trigger['name']}.events")
            if not events or not set(events).issubset(TRIGGER_EVENTS):
                raise ParityVerifierError(f"trigger {trigger['name']} has invalid events")
            if not isinstance(trigger.get("row_level"), bool) or trigger.get("enabled") not in {
                "O",
                "R",
                "A",
            }:
                raise ParityVerifierError(f"trigger {trigger['name']} has invalid execution flags")
            if not isinstance(trigger.get("function"), str):
                raise ParityVerifierError(f"trigger {trigger['name']} requires a function")

        for role_name, privileges in acl.items():
            if role_name != "PUBLIC" and not SAFE_TOKEN_RE.fullmatch(role_name):
                raise ParityVerifierError(f"table {table_name} has an invalid ACL role")
            values = _safe_string_list(privileges, field=f"table {table_name}.acl.{role_name}")
            if not set(values).issubset(TABLE_PRIVILEGES):
                raise ParityVerifierError(f"table {table_name} has invalid privileges for {role_name}")

    seen_functions: set[str] = set()
    for function in functions:
        if not isinstance(function, dict) or not isinstance(function.get("signature"), str):
            raise ParityVerifierError("function entries require a signature")
        signature = _canonical_signature(function["signature"])
        if not signature.startswith("public.") or "(" not in signature or not signature.endswith(")"):
            raise ParityVerifierError(f"invalid function signature: {signature}")
        if signature in seen_functions:
            raise ParityVerifierError(f"duplicate function requirement: {signature}")
        seen_functions.add(signature)
        if function.get("kind") not in FUNCTION_KINDS:
            raise ParityVerifierError(f"function {signature} has invalid kind")
        if function.get("volatility") not in FUNCTION_VOLATILITY:
            raise ParityVerifierError(f"function {signature} has invalid volatility")
        for field in ("owner", "return_type", "language"):
            if not isinstance(function.get(field), str) or not function[field]:
                raise ParityVerifierError(f"function {signature} requires {field}")
        if not isinstance(function.get("security_definer"), bool):
            raise ParityVerifierError(f"function {signature} requires security_definer")
        _safe_string_list(function.get("settings"), field=f"function {signature}.settings")
        _safe_string_list(function.get("execute_roles"), field=f"function {signature}.execute_roles")
        _validate_expression_matcher(
            function.get("definition"), field=f"function {signature}.definition", nullable=False
        )


def _dict_rows(cursor: Any) -> list[dict[str, Any]]:
    names = [str(column.name) for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def read_catalog(connection: Any) -> dict[str, Any]:
    """Read structural metadata only; no product row is selected."""
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '10s'")
            cursor.execute("SELECT current_database(), current_user")
            identity = cursor.fetchone()

            cursor.execute(
                """
                SELECT rolname AS name, rolcanlogin AS login, rolsuper AS superuser,
                       rolcreatedb AS create_database, rolcreaterole AS create_role,
                       rolreplication AS replication, rolbypassrls AS bypass_rls
                FROM pg_catalog.pg_roles
                ORDER BY rolname
                """
            )
            roles = _dict_rows(cursor)
            cursor.execute(
                """
                SELECT member_role.rolname AS member_name, granted_role.rolname AS role_name
                FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS member_role ON member_role.oid = membership.member
                JOIN pg_catalog.pg_roles AS granted_role ON granted_role.oid = membership.roleid
                ORDER BY member_role.rolname, granted_role.rolname
                """
            )
            role_memberships = _dict_rows(cursor)
            cursor.execute(
                """
                SELECT format('%I.%I', namespace.nspname, relation.relname) AS name,
                       relation.relrowsecurity AS rls_enabled,
                       relation.relforcerowsecurity AS rls_forced
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE relation.relkind IN ('r', 'p')
                ORDER BY namespace.nspname, relation.relname
                """
            )
            tables = _dict_rows(cursor)
            cursor.execute(
                """
                SELECT format('%I.%I', namespace.nspname, relation.relname) AS table_name,
                       attribute.attname AS name,
                       pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) AS type,
                       attribute.attnotnull AS not_null,
                       pg_catalog.pg_get_expr(default_entry.adbin, default_entry.adrelid, false) AS default_expression
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                LEFT JOIN pg_catalog.pg_attrdef AS default_entry
                  ON default_entry.adrelid = attribute.attrelid
                 AND default_entry.adnum = attribute.attnum
                WHERE relation.relkind IN ('r', 'p')
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                ORDER BY namespace.nspname, relation.relname, attribute.attnum
                """
            )
            columns = _dict_rows(cursor)
            cursor.execute(
                """
                SELECT format('%I.%I', namespace.nspname, relation.relname) AS table_name,
                       constraint_entry.conname AS name,
                       constraint_entry.contype AS type,
                       constraint_entry.convalidated AS validated,
                       constraint_entry.condeferrable AS deferrable,
                       constraint_entry.condeferred AS initially_deferred,
                       constraint_entry.confupdtype AS on_update,
                       constraint_entry.confdeltype AS on_delete,
                       ARRAY(
                         SELECT attribute.attname
                         FROM unnest(constraint_entry.conkey) WITH ORDINALITY AS key(attnum, position)
                         JOIN pg_catalog.pg_attribute AS attribute
                           ON attribute.attrelid = constraint_entry.conrelid
                          AND attribute.attnum = key.attnum
                         ORDER BY key.position
                       ) AS columns,
                       CASE WHEN constraint_entry.confrelid = 0 THEN NULL
                            ELSE format('%I.%I', reference_namespace.nspname, reference_relation.relname)
                       END AS referenced_table,
                       ARRAY(
                         SELECT attribute.attname
                         FROM unnest(constraint_entry.confkey) WITH ORDINALITY AS key(attnum, position)
                         JOIN pg_catalog.pg_attribute AS attribute
                           ON attribute.attrelid = constraint_entry.confrelid
                          AND attribute.attnum = key.attnum
                         ORDER BY key.position
                       ) AS referenced_columns,
                       pg_catalog.pg_get_expr(
                         constraint_entry.conbin, constraint_entry.conrelid, false
                       ) AS expression
                FROM pg_catalog.pg_constraint AS constraint_entry
                JOIN pg_catalog.pg_class AS relation ON relation.oid = constraint_entry.conrelid
                JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                LEFT JOIN pg_catalog.pg_class AS reference_relation
                  ON reference_relation.oid = constraint_entry.confrelid
                LEFT JOIN pg_catalog.pg_namespace AS reference_namespace
                  ON reference_namespace.oid = reference_relation.relnamespace
                ORDER BY namespace.nspname, relation.relname, constraint_entry.conname
                """
            )
            constraints = _dict_rows(cursor)
            cursor.execute(
                """
                SELECT format('%I.%I', table_namespace.nspname, table_relation.relname) AS table_name,
                       index_relation.relname AS name,
                       index_entry.indisunique AS unique,
                       index_entry.indisvalid AS valid,
                       index_entry.indisready AS ready,
                       ARRAY(
                         SELECT pg_catalog.pg_get_indexdef(
                           index_entry.indexrelid, key_position.position, false
                         )
                         FROM generate_series(1, index_entry.indnkeyatts)
                           AS key_position(position)
                       ) AS keys,
                       pg_catalog.pg_get_expr(
                         index_entry.indpred, index_entry.indrelid, false
                       ) AS predicate
                FROM pg_catalog.pg_index AS index_entry
                JOIN pg_catalog.pg_class AS table_relation ON table_relation.oid = index_entry.indrelid
                JOIN pg_catalog.pg_namespace AS table_namespace
                  ON table_namespace.oid = table_relation.relnamespace
                JOIN pg_catalog.pg_class AS index_relation ON index_relation.oid = index_entry.indexrelid
                ORDER BY table_namespace.nspname, table_relation.relname, index_relation.relname
                """
            )
            indexes = _dict_rows(cursor)
            cursor.execute(
                """
                SELECT format('%I.%I', namespace.nspname, relation.relname) AS table_name,
                       policy.polname AS name,
                       CASE policy.polcmd WHEN '*' THEN 'all' WHEN 'r' THEN 'select'
                         WHEN 'a' THEN 'insert' WHEN 'w' THEN 'update' WHEN 'd' THEN 'delete'
                       END AS command,
                       policy.polpermissive AS permissive,
                       ARRAY(
                         SELECT CASE WHEN policy_role.role_oid = 0
                           THEN 'PUBLIC' ELSE role_entry.rolname END
                         FROM unnest(policy.polroles) AS policy_role(role_oid)
                         LEFT JOIN pg_catalog.pg_roles AS role_entry
                           ON role_entry.oid = policy_role.role_oid
                         ORDER BY CASE WHEN policy_role.role_oid = 0
                           THEN 'PUBLIC' ELSE role_entry.rolname END
                       ) AS roles,
                       pg_catalog.pg_get_expr(policy.polqual, policy.polrelid, false) AS using_expression,
                       pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid, false) AS with_check_expression
                FROM pg_catalog.pg_policy AS policy
                JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
                JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                ORDER BY namespace.nspname, relation.relname, policy.polname
                """
            )
            policies = _dict_rows(cursor)
            cursor.execute(
                """
                SELECT format('%I.%I', namespace.nspname, relation.relname) AS table_name,
                       trigger_entry.tgname AS name,
                       CASE WHEN (trigger_entry.tgtype & 2) <> 0 THEN 'before'
                            WHEN (trigger_entry.tgtype & 64) <> 0 THEN 'instead_of'
                            ELSE 'after' END AS timing,
                       array_remove(ARRAY[
                         CASE WHEN (trigger_entry.tgtype & 4) <> 0 THEN 'insert' END,
                         CASE WHEN (trigger_entry.tgtype & 16) <> 0 THEN 'update' END,
                         CASE WHEN (trigger_entry.tgtype & 8) <> 0 THEN 'delete' END,
                         CASE WHEN (trigger_entry.tgtype & 32) <> 0 THEN 'truncate' END
                       ], NULL) AS events,
                       (trigger_entry.tgtype & 1) <> 0 AS row_level,
                       trigger_entry.tgenabled AS enabled,
                       format('%I.%I(%s)', function_namespace.nspname, routine.proname,
                              pg_catalog.oidvectortypes(routine.proargtypes)) AS function_signature
                FROM pg_catalog.pg_trigger AS trigger_entry
                JOIN pg_catalog.pg_class AS relation ON relation.oid = trigger_entry.tgrelid
                JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                JOIN pg_catalog.pg_proc AS routine ON routine.oid = trigger_entry.tgfoid
                JOIN pg_catalog.pg_namespace AS function_namespace
                  ON function_namespace.oid = routine.pronamespace
                WHERE NOT trigger_entry.tgisinternal
                ORDER BY namespace.nspname, relation.relname, trigger_entry.tgname
                """
            )
            triggers = _dict_rows(cursor)
            cursor.execute(
                """
                SELECT format('%I.%I', namespace.nspname, relation.relname) AS table_name,
                       CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE grantee.rolname END AS grantee,
                       acl.privilege_type
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                  coalesce(relation.relacl, pg_catalog.acldefault('r', relation.relowner))
                ) AS acl
                LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
                WHERE relation.relkind IN ('r', 'p')
                ORDER BY namespace.nspname, relation.relname, grantee
                """
            )
            table_acl = _dict_rows(cursor)
            cursor.execute(
                """
                SELECT format('%I.%I', namespace.nspname, relation.relname) AS table_name,
                       attribute.attname AS column_name,
                       CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE grantee.rolname END AS grantee,
                       acl.privilege_type
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS acl
                LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
                WHERE attribute.attnum > 0 AND NOT attribute.attisdropped
                ORDER BY namespace.nspname, relation.relname, attribute.attnum, grantee
                """
            )
            column_acl = _dict_rows(cursor)
            cursor.execute(
                """
                SELECT format('%I.%I(%s)', namespace.nspname, routine.proname,
                              pg_catalog.oidvectortypes(routine.proargtypes)) AS signature,
                       CASE routine.prokind WHEN 'p' THEN 'procedure' ELSE 'function' END AS kind,
                       owner.rolname AS owner,
                       pg_catalog.pg_get_function_result(routine.oid) AS return_type,
                       language.lanname AS language,
                       routine.prosecdef AS security_definer,
                       CASE routine.provolatile WHEN 'i' THEN 'immutable'
                         WHEN 's' THEN 'stable' ELSE 'volatile' END AS volatility,
                       coalesce(routine.proconfig, ARRAY[]::text[]) AS settings,
                       pg_catalog.pg_get_functiondef(routine.oid) AS definition
                FROM pg_catalog.pg_proc AS routine
                JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = routine.pronamespace
                JOIN pg_catalog.pg_roles AS owner ON owner.oid = routine.proowner
                JOIN pg_catalog.pg_language AS language ON language.oid = routine.prolang
                WHERE routine.prokind IN ('f', 'p')
                ORDER BY namespace.nspname, routine.proname, routine.oid
                """
            )
            functions = _dict_rows(cursor)
            cursor.execute(
                """
                SELECT format('%I.%I(%s)', namespace.nspname, routine.proname,
                              pg_catalog.oidvectortypes(routine.proargtypes)) AS signature,
                       CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE grantee.rolname END AS grantee
                FROM pg_catalog.pg_proc AS routine
                JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = routine.pronamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                  coalesce(routine.proacl, pg_catalog.acldefault('f', routine.proowner))
                ) AS acl
                LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
                WHERE routine.prokind IN ('f', 'p') AND acl.privilege_type = 'EXECUTE'
                ORDER BY namespace.nspname, routine.proname, routine.oid, grantee
                """
            )
            function_acl = _dict_rows(cursor)

    return {
        "database_name": str(identity[0]),
        "current_user": str(identity[1]),
        "roles": roles,
        "role_memberships": role_memberships,
        "tables": tables,
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
        "policies": policies,
        "triggers": triggers,
        "table_acl": table_acl,
        "column_acl": column_acl,
        "functions": functions,
        "function_acl": function_acl,
    }


def _matches_expression(expectation: object, actual: object) -> bool:
    if expectation is None:
        return actual is None
    if not isinstance(expectation, Mapping):
        return False
    normalized_actual = _normalize_sql(actual)
    if normalized_actual is None:
        return False
    exact = expectation.get("exact")
    if exact is not None and normalized_actual != _normalize_sql(exact):
        return False
    for fragment in expectation.get("required", []):
        if _normalize_sql(fragment) not in normalized_actual:
            return False
    for fragment in expectation.get("forbidden", []):
        if _normalize_sql(fragment) in normalized_actual:
            return False
    return True


def _sorted_strings(values: Iterable[object]) -> list[str]:
    return sorted(str(value) for value in values)


def build_report(contract: Mapping[str, Any], catalog: Mapping[str, Any]) -> dict[str, Any]:
    present: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []

    def record(kind: str, name: str, requirement: str, satisfied: bool, reason: str) -> None:
        item = {"kind": kind, "name": name, "requirement": requirement}
        if not satisfied:
            item["reason"] = reason
        (present if satisfied else missing).append(item)

    expected_database = str(contract["database_name"])
    actual_database = str(catalog.get("database_name") or "")
    record(
        "database",
        expected_database,
        "identity",
        actual_database == expected_database,
        "database identity does not match the parity contract",
    )
    current_user = str(catalog.get("current_user") or "")
    forbidden_connection_roles = contract["connection_identity"]["must_not_equal_roles"]
    record(
        "connection_identity",
        current_user or "<unknown>",
        "separation_of_duties",
        bool(current_user) and current_user not in forbidden_connection_roles,
        "verifier must connect as the installer/verification identity, not a runtime or definer role",
    )

    roles = {str(row["name"]): row for row in catalog.get("roles", [])}
    memberships: dict[str, list[str]] = defaultdict(list)
    for row in catalog.get("role_memberships", []):
        memberships[str(row["member_name"])].append(str(row["role_name"]))
    for expected in contract["roles"]:
        role_name = str(expected["name"])
        actual = roles.get(role_name)
        attributes_match = actual is not None and all(
            bool(actual.get(attribute)) == expected[attribute] for attribute in ROLE_ATTRIBUTES
        )
        record(
            "role",
            role_name,
            "object_and_attributes",
            attributes_match,
            "role is absent or has incorrect security attributes",
        )
        record(
            "role_membership",
            role_name,
            "member_of",
            _sorted_strings(memberships.get(role_name, [])) == _sorted_strings(expected["member_of"]),
            "role membership differs from the least-privilege contract",
        )

    tables = {str(row["name"]): row for row in catalog.get("tables", [])}
    columns = {
        (str(row["table_name"]), str(row["name"])): row for row in catalog.get("columns", [])
    }
    constraints = {
        (str(row["table_name"]), str(row["name"])): row
        for row in catalog.get("constraints", [])
    }
    indexes = {
        (str(row["table_name"]), str(row["name"])): row for row in catalog.get("indexes", [])
    }
    policies_by_table: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in catalog.get("policies", []):
        policies_by_table[str(row["table_name"])][str(row["name"])] = row
    triggers_by_table: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in catalog.get("triggers", []):
        triggers_by_table[str(row["table_name"])][str(row["name"])] = row
    table_acl: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in catalog.get("table_acl", []):
        table_acl[(str(row["table_name"]), str(row["grantee"]))].add(
            str(row["privilege_type"]).upper()
        )
    column_acl: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in catalog.get("column_acl", []):
        column_acl[(str(row["table_name"]), str(row["grantee"]))][
            str(row["column_name"])
        ].add(str(row["privilege_type"]).upper())

    for expected_table in contract["tables"]:
        table_name = str(expected_table["name"])
        actual_table = tables.get(table_name)
        record("table", table_name, "object", actual_table is not None, "table is absent")
        for expected_column in expected_table["columns"]:
            column_name = str(expected_column["name"])
            actual = columns.get((table_name, column_name))
            satisfied = (
                actual is not None
                and _normalize_sql(actual.get("type")) == _normalize_sql(expected_column["type"])
                and bool(actual.get("not_null")) == expected_column["not_null"]
                and _normalize_sql(actual.get("default_expression"))
                == _normalize_sql(expected_column["default"])
            )
            record(
                "column",
                f"{table_name}.{column_name}",
                "type_nullability_default",
                satisfied,
                "column is absent or its type/nullability/default differs",
            )

        for expected_constraint in expected_table["constraints"]:
            constraint_name = str(expected_constraint["name"])
            actual = constraints.get((table_name, constraint_name))
            satisfied = actual is not None
            if satisfied:
                satisfied = str(actual.get("type")) == CONSTRAINT_TYPES[expected_constraint["category"]]
                satisfied = satisfied and bool(actual.get("validated")) == expected_constraint["validated"]
                if "columns" in expected_constraint:
                    satisfied = satisfied and list(actual.get("columns") or []) == expected_constraint["columns"]
                if "deferrable" in expected_constraint:
                    satisfied = satisfied and bool(actual.get("deferrable")) == expected_constraint["deferrable"]
                if "initially_deferred" in expected_constraint:
                    satisfied = (
                        satisfied
                        and bool(actual.get("initially_deferred"))
                        == expected_constraint["initially_deferred"]
                    )
                if "on_update" in expected_constraint:
                    satisfied = satisfied and actual.get("on_update") == expected_constraint["on_update"]
                if "on_delete" in expected_constraint:
                    satisfied = satisfied and actual.get("on_delete") == expected_constraint["on_delete"]
                reference = expected_constraint.get("references")
                if reference is not None:
                    satisfied = satisfied and actual.get("referenced_table") == reference["table"]
                    satisfied = satisfied and list(actual.get("referenced_columns") or []) == reference["columns"]
                if expected_constraint["category"] == "check":
                    satisfied = satisfied and _matches_expression(
                        expected_constraint["expression"], actual.get("expression")
                    )
            record(
                "constraint",
                f"{table_name}.{constraint_name}",
                str(expected_constraint["category"]),
                satisfied,
                "constraint is absent, unvalidated, weakened, or has incorrect key/action semantics",
            )

        for expected_index in expected_table.get("indexes", []):
            index_name = str(expected_index["name"])
            actual = indexes.get((table_name, index_name))
            satisfied = (
                actual is not None
                and bool(actual.get("unique")) == expected_index["unique"]
                and bool(actual.get("valid")) == expected_index["valid"]
                and bool(actual.get("ready")) == expected_index["ready"]
                and [_normalize_sql(value) for value in actual.get("keys") or []]
                == [_normalize_sql(value) for value in expected_index["keys"]]
                and _matches_expression(expected_index["predicate"], actual.get("predicate"))
            )
            record(
                "index",
                f"{table_name}.{index_name}",
                "keys_expression_predicate",
                satisfied,
                "index is absent, invalid, or has incorrect keys/expression/predicate",
            )

        rls = expected_table["rls"]
        record(
            "rls",
            table_name,
            "enabled",
            actual_table is not None and bool(actual_table.get("rls_enabled")) == rls["enabled"],
            "RLS enablement differs",
        )
        record(
            "rls",
            table_name,
            "forced",
            actual_table is not None and bool(actual_table.get("rls_forced")) == rls["forced"],
            "FORCE RLS differs",
        )

        actual_policies = policies_by_table.get(table_name, {})
        expected_policy_names = _sorted_strings(policy["name"] for policy in expected_table["policies"])
        record(
            "policy_set",
            table_name,
            "exact_names",
            _sorted_strings(actual_policies) == expected_policy_names,
            "policy set differs; missing or extra policies can weaken or disable isolation",
        )
        for expected_policy in expected_table["policies"]:
            policy_name = str(expected_policy["name"])
            actual = actual_policies.get(policy_name)
            satisfied = (
                actual is not None
                and actual.get("command") == expected_policy["command"]
                and bool(actual.get("permissive")) == expected_policy["permissive"]
                and _sorted_strings(actual.get("roles") or [])
                == _sorted_strings(expected_policy["roles"])
                and _matches_expression(expected_policy["using"], actual.get("using_expression"))
                and _matches_expression(
                    expected_policy["with_check"], actual.get("with_check_expression")
                )
            )
            record(
                "policy",
                f"{table_name}.{policy_name}",
                "command_roles_expressions",
                satisfied,
                "policy is absent or its command/roles/USING/WITH CHECK differs",
            )

        actual_triggers = triggers_by_table.get(table_name, {})
        expected_trigger_names = _sorted_strings(trigger["name"] for trigger in expected_table["triggers"])
        record(
            "trigger_set",
            table_name,
            "exact_names",
            _sorted_strings(actual_triggers) == expected_trigger_names,
            "trigger set differs; invariant or revocation guards are missing/extra",
        )
        for expected_trigger in expected_table["triggers"]:
            trigger_name = str(expected_trigger["name"])
            actual = actual_triggers.get(trigger_name)
            satisfied = (
                actual is not None
                and actual.get("timing") == expected_trigger["timing"]
                and _sorted_strings(actual.get("events") or [])
                == _sorted_strings(expected_trigger["events"])
                and bool(actual.get("row_level")) == expected_trigger["row_level"]
                and actual.get("enabled") == expected_trigger["enabled"]
                and _canonical_signature(str(actual.get("function_signature") or ""))
                == _canonical_signature(expected_trigger["function"])
            )
            record(
                "trigger",
                f"{table_name}.{trigger_name}",
                "timing_events_function_enabled",
                satisfied,
                "trigger is absent, disabled, or bound to incorrect events/function",
            )

        for role_name, expected_privileges in expected_table["acl"].items():
            actual_privileges = _sorted_strings(table_acl.get((table_name, role_name), set()))
            record(
                "table_acl",
                f"{table_name}:{role_name}",
                "exact_privileges",
                actual_privileges == _sorted_strings(expected_privileges),
                "table privileges differ from the least-privilege contract",
            )
        for role_name, expected_columns in expected_table.get("column_acl", {}).items():
            actual_columns = {
                column: _sorted_strings(privileges)
                for column, privileges in column_acl.get((table_name, role_name), {}).items()
            }
            normalized_expected = {
                column: _sorted_strings(privileges) for column, privileges in expected_columns.items()
            }
            record(
                "column_acl",
                f"{table_name}:{role_name}",
                "exact_privileges",
                actual_columns == normalized_expected,
                "column privileges differ from the narrow update contract",
            )

    functions = {
        _canonical_signature(str(row["signature"])): row for row in catalog.get("functions", [])
    }
    function_acl: dict[str, list[str]] = defaultdict(list)
    for row in catalog.get("function_acl", []):
        function_acl[_canonical_signature(str(row["signature"]))].append(str(row["grantee"]))
    for expected_function in contract["functions"]:
        signature = _canonical_signature(str(expected_function["signature"]))
        actual = functions.get(signature)
        satisfied = (
            actual is not None
            and actual.get("kind") == expected_function["kind"]
            and actual.get("owner") == expected_function["owner"]
            and _normalize_sql(actual.get("return_type"))
            == _normalize_sql(expected_function["return_type"])
            and actual.get("language") == expected_function["language"]
            and bool(actual.get("security_definer")) == expected_function["security_definer"]
            and actual.get("volatility") == expected_function["volatility"]
            and _sorted_strings(actual.get("settings") or [])
            == _sorted_strings(expected_function["settings"])
            and _matches_expression(expected_function["definition"], actual.get("definition"))
        )
        record(
            "function",
            signature,
            "kind_owner_return_security_search_path_definition",
            satisfied,
            "function is absent or its kind/owner/return/security/search_path/definition differs",
        )
        record(
            "function_acl",
            signature,
            "exact_execute_roles",
            _sorted_strings(function_acl.get(signature, []))
            == _sorted_strings(expected_function["execute_roles"]),
            "function EXECUTE ACL differs, including possible PUBLIC exposure",
        )

    def order_key(item: Mapping[str, str]) -> tuple[str, str, str]:
        return item["kind"], item["name"], item["requirement"]

    present.sort(key=order_key)
    missing.sort(key=order_key)
    return {
        "report_version": 2,
        "schema_generation": contract["schema_generation"],
        "domain": contract["domain"],
        "database_name": actual_database,
        "status": "present" if not missing else "missing",
        "summary": {
            "expected": len(present) + len(missing),
            "present": len(present),
            "missing": len(missing),
        },
        "present": present,
        "missing": missing,
    }


def render_report(report: Mapping[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def _validate_pg_environment(environment: Mapping[str, str]) -> None:
    missing = [name for name in REQUIRED_PG_ENVIRONMENT if not environment.get(name, "").strip()]
    if missing:
        raise ParityVerifierError("missing required PostgreSQL settings: " + ", ".join(missing))
    if environment["PGDATABASE"] != EXPECTED_DATABASE_NAME:
        raise ParityVerifierError("PGDATABASE must remain fixed at geno_v2")
    try:
        port = int(environment["PGPORT"])
    except ValueError as exc:
        raise ParityVerifierError("PGPORT must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise ParityVerifierError("PGPORT must be an integer between 1 and 65535")


def _connect() -> Any:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - production images supply psycopg.
        raise ParityVerifierError("psycopg is required") from exc
    _validate_pg_environment(os.environ)
    try:
        return psycopg.connect(
            host=os.environ["PGHOST"],
            port=os.environ["PGPORT"],
            dbname=os.environ["PGDATABASE"],
            user=os.environ["PGUSER"],
            password=os.environ["PGPASSWORD"],
            connect_timeout=5,
        )
    except Exception as exc:
        raise ParityVerifierError("database connection failed") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True, help="parity domain, currently auth")
    parser.add_argument(
        "--contract-root",
        type=Path,
        default=DEFAULT_CONTRACT_ROOT,
        help="directory containing <domain>.json parity contracts",
    )
    parser.add_argument(
        "--report-json",
        nargs="?",
        const="-",
        metavar="PATH",
        help="write deterministic JSON to PATH, or stdout when PATH is omitted",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        contract = load_contract(args.contract_root, args.domain)
        connection = _connect()
        try:
            catalog = read_catalog(connection)
        except Exception as exc:
            raise ParityVerifierError("catalog query failed") from exc
        finally:
            try:
                connection.close()
            except Exception:
                pass
        report = build_report(contract, catalog)
        rendered = render_report(report)
        if args.report_json is None or args.report_json == "-":
            sys.stdout.write(rendered)
        else:
            try:
                Path(args.report_json).write_text(rendered, encoding="utf-8")
            except OSError as exc:
                raise ParityVerifierError("cannot write parity report") from exc
        return 0 if report["status"] == "present" else 1
    except ParityVerifierError as exc:
        sys.stderr.write(f"schema-v2 parity error: {exc}\n")
        return 2
    except Exception:
        sys.stderr.write("schema-v2 parity error: verifier failed\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
