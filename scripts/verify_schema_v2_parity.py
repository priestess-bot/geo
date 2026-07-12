#!/usr/bin/env python3
"""Verify a Schema v2 domain parity contract against PostgreSQL catalogs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT_ROOT = ROOT / "infra/db/schema-v2/parity"
REQUIRED_PG_ENVIRONMENT = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
QUALIFIED_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$")
ROLE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
CONSTRAINT_TYPES = {
    "primary_key": "p",
    "unique": "u",
    "foreign_key": "f",
    "composite_foreign_key": "f",
    "deferrable_composite_foreign_key": "f",
    "check": "c",
}


class ParityVerifierError(RuntimeError):
    """Raised when the verifier cannot safely produce a parity report."""


def _canonical_signature(value: str) -> str:
    return re.sub(r"\s*,\s*", ",", value.strip())


def load_contract(contract_root: Path, domain: str) -> dict[str, Any]:
    if not ROLE_NAME_RE.fullmatch(domain):
        raise ParityVerifierError(
            "domain must contain only lowercase letters, digits, and underscores"
        )
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
    if payload.get("contract_version") != 1:
        raise ParityVerifierError("unsupported parity contract version")
    if payload.get("schema_generation") != 2:
        raise ParityVerifierError("parity contract schema_generation must be 2")
    if payload.get("domain") != domain:
        raise ParityVerifierError("parity contract domain does not match the requested domain")
    if payload.get("database_name") != "geno_v2":
        raise ParityVerifierError("parity contract database_name must remain geno_v2")

    roles = payload.get("roles")
    tables = payload.get("tables")
    functions = payload.get("functions")
    if (
        not isinstance(roles, list)
        or not isinstance(tables, list)
        or not isinstance(functions, list)
    ):
        raise ParityVerifierError("roles, tables, and functions must be lists")

    role_names: set[str] = set()
    for role in roles:
        if not isinstance(role, dict) or not ROLE_NAME_RE.fullmatch(str(role.get("name", ""))):
            raise ParityVerifierError("role entries require a safe name")
        role_name = str(role["name"])
        if role_name in role_names:
            raise ParityVerifierError(f"duplicate role requirement: {role_name}")
        role_names.add(role_name)
        for attribute in (
            "login",
            "superuser",
            "create_database",
            "create_role",
            "replication",
            "bypass_rls",
        ):
            if not isinstance(role.get(attribute), bool):
                raise ParityVerifierError(f"role {role_name} requires boolean {attribute}")

    table_names: set[str] = set()
    for table in tables:
        if not isinstance(table, dict) or not QUALIFIED_NAME_RE.fullmatch(
            str(table.get("name", ""))
        ):
            raise ParityVerifierError("table entries require a schema-qualified safe name")
        table_name = str(table["name"])
        if table_name in table_names:
            raise ParityVerifierError(f"duplicate table requirement: {table_name}")
        table_names.add(table_name)
        columns = table.get("required_columns")
        constraints = table.get("constraints")
        indexes = table.get("indexes", [])
        rls = table.get("rls")
        if (
            not isinstance(columns, list)
            or not all(ROLE_NAME_RE.fullmatch(str(column)) for column in columns)
            or len(columns) != len(set(columns))
        ):
            raise ParityVerifierError(f"table {table_name} has invalid required_columns")
        if not isinstance(constraints, list) or not isinstance(indexes, list):
            raise ParityVerifierError(f"table {table_name} constraints and indexes must be lists")
        if not isinstance(rls, dict) or not all(
            isinstance(rls.get(key), bool) for key in ("enabled", "forced")
        ):
            raise ParityVerifierError(f"table {table_name} requires boolean RLS expectations")

        requirement_names: set[str] = set()
        for constraint in constraints:
            if not isinstance(constraint, dict):
                raise ParityVerifierError(f"table {table_name} has an invalid constraint")
            name = str(constraint.get("name", ""))
            category = constraint.get("category")
            if not ROLE_NAME_RE.fullmatch(name) or category not in CONSTRAINT_TYPES:
                raise ParityVerifierError(
                    f"table {table_name} has an invalid constraint requirement"
                )
            if name in requirement_names:
                raise ParityVerifierError(f"table {table_name} repeats requirement {name}")
            requirement_names.add(name)
        for index in indexes:
            if not isinstance(index, dict) or not ROLE_NAME_RE.fullmatch(
                str(index.get("name", ""))
            ):
                raise ParityVerifierError(f"table {table_name} has an invalid index requirement")
            if not isinstance(index.get("unique"), bool) or not isinstance(
                index.get("partial"), bool
            ):
                raise ParityVerifierError(f"table {table_name} index flags must be boolean")

    function_signatures: set[str] = set()
    for function in functions:
        if not isinstance(function, dict) or not isinstance(function.get("signature"), str):
            raise ParityVerifierError("function entries require a signature")
        signature = _canonical_signature(function["signature"])
        if (
            not signature.startswith("public.")
            or "(" not in signature
            or not signature.endswith(")")
        ):
            raise ParityVerifierError(f"invalid function signature: {signature}")
        if signature in function_signatures:
            raise ParityVerifierError(f"duplicate function requirement: {signature}")
        function_signatures.add(signature)
        if not isinstance(function.get("security_definer"), bool):
            raise ParityVerifierError(f"function {signature} requires security_definer")


def _dict_rows(cursor: Any) -> list[dict[str, Any]]:
    names = [str(column.name) for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def read_catalog(connection: Any) -> dict[str, Any]:
    """Read only structural metadata; no product rows are queried."""
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '10s'")
            cursor.execute("SELECT current_database() AS database_name")
            database_name = str(cursor.fetchone()[0])

            cursor.execute(
                """
                SELECT
                    rolname AS name,
                    rolcanlogin AS login,
                    rolsuper AS superuser,
                    rolcreatedb AS create_database,
                    rolcreaterole AS create_role,
                    rolreplication AS replication,
                    rolbypassrls AS bypass_rls
                FROM pg_catalog.pg_roles
                ORDER BY rolname
                """
            )
            roles = _dict_rows(cursor)

            cursor.execute(
                """
                SELECT
                    format('%I.%I', namespace.nspname, relation.relname) AS name,
                    relation.relrowsecurity AS rls_enabled,
                    relation.relforcerowsecurity AS rls_forced
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE relation.relkind IN ('r', 'p')
                ORDER BY namespace.nspname, relation.relname
                """
            )
            tables = _dict_rows(cursor)

            cursor.execute(
                """
                SELECT
                    format('%I.%I', namespace.nspname, relation.relname) AS table_name,
                    attribute.attname AS name
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE relation.relkind IN ('r', 'p')
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                ORDER BY namespace.nspname, relation.relname, attribute.attnum
                """
            )
            columns = _dict_rows(cursor)

            cursor.execute(
                """
                SELECT
                    format('%I.%I', namespace.nspname, relation.relname) AS table_name,
                    constraint_entry.conname AS name,
                    constraint_entry.contype AS type,
                    constraint_entry.condeferrable AS deferrable,
                    constraint_entry.condeferred AS initially_deferred,
                    ARRAY(
                        SELECT attribute.attname
                        FROM unnest(constraint_entry.conkey) WITH ORDINALITY AS key(attnum, position)
                        JOIN pg_catalog.pg_attribute AS attribute
                          ON attribute.attrelid = constraint_entry.conrelid
                         AND attribute.attnum = key.attnum
                        ORDER BY key.position
                    ) AS columns,
                    CASE
                        WHEN constraint_entry.confrelid = 0 THEN NULL
                        ELSE format('%I.%I', reference_namespace.nspname, reference_relation.relname)
                    END AS referenced_table,
                    ARRAY(
                        SELECT attribute.attname
                        FROM unnest(constraint_entry.confkey) WITH ORDINALITY AS key(attnum, position)
                        JOIN pg_catalog.pg_attribute AS attribute
                          ON attribute.attrelid = constraint_entry.confrelid
                         AND attribute.attnum = key.attnum
                        ORDER BY key.position
                    ) AS referenced_columns
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
                SELECT
                    format('%I.%I', table_namespace.nspname, table_relation.relname) AS table_name,
                    index_relation.relname AS name,
                    index_entry.indisunique AS unique,
                    index_entry.indpred IS NOT NULL AS partial
                FROM pg_catalog.pg_index AS index_entry
                JOIN pg_catalog.pg_class AS table_relation
                  ON table_relation.oid = index_entry.indrelid
                JOIN pg_catalog.pg_namespace AS table_namespace
                  ON table_namespace.oid = table_relation.relnamespace
                JOIN pg_catalog.pg_class AS index_relation
                  ON index_relation.oid = index_entry.indexrelid
                ORDER BY table_namespace.nspname, table_relation.relname, index_relation.relname
                """
            )
            indexes = _dict_rows(cursor)

            cursor.execute(
                """
                SELECT
                    format(
                        '%I.%I(%s)',
                        namespace.nspname,
                        routine.proname,
                        pg_catalog.oidvectortypes(routine.proargtypes)
                    ) AS signature,
                    routine.prosecdef AS security_definer
                FROM pg_catalog.pg_proc AS routine
                JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = routine.pronamespace
                ORDER BY namespace.nspname, routine.proname, routine.oid
                """
            )
            functions = _dict_rows(cursor)

    return {
        "database_name": database_name,
        "roles": roles,
        "tables": tables,
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
        "functions": functions,
    }


def _report_item(
    kind: str, name: str, requirement: str, *, reason: str | None = None
) -> dict[str, str]:
    item = {"kind": kind, "name": name, "requirement": requirement}
    if reason is not None:
        item["reason"] = reason
    return item


def build_report(contract: Mapping[str, Any], catalog: Mapping[str, Any]) -> dict[str, Any]:
    present: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []

    def record(kind: str, name: str, requirement: str, satisfied: bool, reason: str) -> None:
        destination = present if satisfied else missing
        destination.append(
            _report_item(kind, name, requirement, reason=None if satisfied else reason)
        )

    expected_database = str(contract["database_name"])
    actual_database = str(catalog.get("database_name") or "")
    record(
        "database",
        expected_database,
        "identity",
        actual_database == expected_database,
        "database identity does not match the parity contract",
    )

    roles = {str(row["name"]): row for row in catalog.get("roles", [])}
    for expected in contract["roles"]:
        role_name = str(expected["name"])
        actual = roles.get(role_name)
        attributes = (
            "login",
            "superuser",
            "create_database",
            "create_role",
            "replication",
            "bypass_rls",
        )
        satisfied = actual is not None and all(
            bool(actual.get(key)) == expected[key] for key in attributes
        )
        record(
            "role",
            role_name,
            "object_and_attributes",
            satisfied,
            "role is absent or has unsafe attributes",
        )

    tables = {str(row["name"]): row for row in catalog.get("tables", [])}
    columns = {(str(row["table_name"]), str(row["name"])) for row in catalog.get("columns", [])}
    constraints = {
        (str(row["table_name"]), str(row["name"])): row for row in catalog.get("constraints", [])
    }
    indexes = {
        (str(row["table_name"]), str(row["name"])): row for row in catalog.get("indexes", [])
    }
    for expected_table in contract["tables"]:
        table_name = str(expected_table["name"])
        actual_table = tables.get(table_name)
        record("table", table_name, "object", actual_table is not None, "table is absent")
        for column_name in expected_table["required_columns"]:
            qualified_column = f"{table_name}.{column_name}"
            record(
                "column",
                qualified_column,
                "required_column",
                (table_name, column_name) in columns,
                "required column is absent",
            )
        for expected_constraint in expected_table["constraints"]:
            constraint_name = str(expected_constraint["name"])
            actual = constraints.get((table_name, constraint_name))
            satisfied = actual is not None
            if satisfied:
                satisfied = (
                    str(actual.get("type")) == CONSTRAINT_TYPES[expected_constraint["category"]]
                )
                expected_columns = expected_constraint.get("columns")
                if expected_columns is not None:
                    satisfied = satisfied and list(actual.get("columns") or []) == expected_columns
                reference = expected_constraint.get("references")
                if reference is not None:
                    satisfied = satisfied and actual.get("referenced_table") == reference["table"]
                    satisfied = (
                        satisfied
                        and list(actual.get("referenced_columns") or []) == reference["columns"]
                    )
                if "deferrable" in expected_constraint:
                    satisfied = (
                        satisfied
                        and bool(actual.get("deferrable")) == expected_constraint["deferrable"]
                    )
                if "initially_deferred" in expected_constraint:
                    satisfied = (
                        satisfied
                        and bool(actual.get("initially_deferred"))
                        == expected_constraint["initially_deferred"]
                    )
            record(
                "constraint",
                f"{table_name}.{constraint_name}",
                str(expected_constraint["category"]),
                satisfied,
                "constraint is absent or does not match its key contract",
            )
        for expected_index in expected_table.get("indexes", []):
            index_name = str(expected_index["name"])
            actual = indexes.get((table_name, index_name))
            satisfied = (
                actual is not None
                and bool(actual.get("unique")) == expected_index["unique"]
                and bool(actual.get("partial")) == expected_index["partial"]
            )
            record(
                "index",
                f"{table_name}.{index_name}",
                str(expected_index["category"]),
                satisfied,
                "index is absent or does not match its uniqueness/predicate contract",
            )
        rls = expected_table["rls"]
        record(
            "rls",
            table_name,
            "enabled",
            actual_table is not None and bool(actual_table.get("rls_enabled")) == rls["enabled"],
            "RLS enablement does not match",
        )
        record(
            "rls",
            table_name,
            "forced",
            actual_table is not None and bool(actual_table.get("rls_forced")) == rls["forced"],
            "FORCE RLS does not match",
        )

    functions = {
        _canonical_signature(str(row["signature"])): row for row in catalog.get("functions", [])
    }
    for expected_function in contract["functions"]:
        signature = _canonical_signature(str(expected_function["signature"]))
        actual = functions.get(signature)
        satisfied = (
            actual is not None
            and bool(actual.get("security_definer")) == expected_function["security_definer"]
        )
        record(
            "function",
            signature,
            "object_and_security_mode",
            satisfied,
            "function is absent or has the wrong security mode",
        )

    def order_key(item: Mapping[str, str]) -> tuple[str, str, str]:
        return item["kind"], item["name"], item["requirement"]

    present.sort(key=order_key)
    missing.sort(key=order_key)
    return {
        "report_version": 1,
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


def _connect(*, database_url: str | None) -> Any:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - production image supplies psycopg.
        raise ParityVerifierError("psycopg is required") from exc

    try:
        if database_url:
            return psycopg.connect(database_url, connect_timeout=5)
        missing = [name for name in REQUIRED_PG_ENVIRONMENT if not os.getenv(name, "").strip()]
        if missing:
            raise ParityVerifierError("missing required PostgreSQL settings: " + ", ".join(missing))
        return psycopg.connect(
            host=os.environ["PGHOST"],
            port=os.environ["PGPORT"],
            dbname=os.environ["PGDATABASE"],
            user=os.environ["PGUSER"],
            password=os.environ["PGPASSWORD"],
            connect_timeout=5,
        )
    except ParityVerifierError:
        raise
    except Exception as exc:
        raise ParityVerifierError("database connection failed") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True, help="parity domain, currently auth")
    parser.add_argument(
        "--database-url",
        help="optional PostgreSQL URL; structured PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD are the default",
    )
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
        connection = _connect(database_url=args.database_url)
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
