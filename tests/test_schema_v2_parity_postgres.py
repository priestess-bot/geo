"""Synthetic PostgreSQL catalog adversarial test, not an Auth behavior test."""

from __future__ import annotations

import os
import hashlib
from contextlib import contextmanager
from uuid import uuid4

import pytest

from scripts.verify_schema_v2_parity import _normalize_sql, build_report, read_catalog


pytestmark = pytest.mark.skipif(
    os.getenv("SCHEMA_V2_PARITY_POSTGRES_TEST") != "1",
    reason="SCHEMA_V2_PARITY_POSTGRES_TEST=1 is required",
)


def _connection_parameters() -> dict[str, object]:
    required = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        pytest.skip("missing structured PostgreSQL settings: " + ", ".join(missing))
    if os.environ["PGDATABASE"] != "geno_v2":
        pytest.skip("real parity behavior test is restricted to disposable geno_v2")
    return {
        "host": os.environ["PGHOST"],
        "port": os.environ["PGPORT"],
        "dbname": os.environ["PGDATABASE"],
        "user": os.environ["PGUSER"],
        "password": os.environ["PGPASSWORD"],
        "connect_timeout": 5,
    }


def _contract(schema: str, owner: str, definition_sha256: str) -> dict[str, object]:
    table = f"{schema}.secure_items"
    function = f"{schema}.guard_secure_item()"
    return {
        "contract_version": 2,
        "schema_generation": 2,
        "domain": "auth",
        "database_name": "geno_v2",
        "contract_mode": "synthetic_fixture",
        "source_parity": {"mappings": []},
        "v2_hardening": {"deviations": []},
        "connection_identity": {
            "must_not_equal_roles": [],
            "runtime_identity_mapping": {
                "source_role": "runtime_app",
                "target_role": "runtime_app",
                "compatibility_status": "ready",
            },
        },
        "roles": [],
        "tables": [
            {
                "name": table,
                "columns": [
                    {"name": "id", "type": "integer", "not_null": True, "default": None},
                    {
                        "name": "tenant_id",
                        "type": "integer",
                        "not_null": True,
                        "default": None,
                    },
                    {
                        "name": "label",
                        "type": "text",
                        "not_null": True,
                        "default": "'pending'::text",
                    },
                ],
                "constraints": [
                    {
                        "name": "secure_items_pkey",
                        "category": "primary_key",
                        "columns": ["id"],
                        "validated": True,
                    },
                    {
                        "name": "secure_items_label_check",
                        "category": "check",
                        "validated": True,
                        "expression": {
                            "exact": "(label = ANY (ARRAY['pending'::text, 'complete'::text]))"
                        },
                    },
                ],
                "indexes": [
                    {
                        "name": "secure_items_label_unique",
                        "unique": True,
                        "valid": True,
                        "ready": True,
                        "keys": ["tenant_id", "lower(label)"],
                        "predicate": {"exact": "(label <> 'deleted'::text)"},
                    }
                ],
                "rls": {"enabled": True, "forced": True},
                "policies": [
                    {
                        "name": "secure_items_select",
                        "command": "select",
                        "permissive": True,
                        "roles": ["PUBLIC"],
                        "using": {
                            "exact": "(tenant_id = "
                            "(current_setting('app.tenant_id'::text, true))::integer)"
                        },
                        "with_check": None,
                    }
                ],
                "triggers": [
                    {
                        "name": "secure_items_guard",
                        "timing": "before",
                        "events": ["insert", "update"],
                        "row_level": True,
                        "enabled": "O",
                        "function": function,
                    }
                ],
                "acl": {"PUBLIC": []},
            }
        ],
        "functions": [
            {
                "signature": function,
                "kind": "function",
                "owner": owner,
                "return_type": "trigger",
                "language": "plpgsql",
                "security_definer": True,
                "volatility": "volatile",
                "settings": ["search_path=pg_catalog"],
                "execute_roles": [owner],
                "definition": {"sha256": definition_sha256},
            }
        ],
    }


@contextmanager
def _fixture_schema(connection: object, schema: str):
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE SCHEMA {schema}")
        cursor.execute(
            f"""
            CREATE TABLE {schema}.secure_items (
              id integer NOT NULL,
              tenant_id integer NOT NULL,
              label text NOT NULL DEFAULT 'pending',
              CONSTRAINT secure_items_pkey PRIMARY KEY (id),
              CONSTRAINT secure_items_label_check
                CHECK (label = ANY (ARRAY['pending'::text, 'complete'::text]))
            )
            """
        )
        cursor.execute(
            f"CREATE UNIQUE INDEX secure_items_label_unique "
            f"ON {schema}.secure_items (tenant_id, lower(label)) "
            "WHERE label <> 'deleted'::text"
        )
        cursor.execute(f"ALTER TABLE {schema}.secure_items ENABLE ROW LEVEL SECURITY")
        cursor.execute(f"ALTER TABLE {schema}.secure_items FORCE ROW LEVEL SECURITY")
        cursor.execute(
            f"CREATE POLICY secure_items_select ON {schema}.secure_items "
            "FOR SELECT TO PUBLIC USING ("
            "tenant_id = current_setting('app.tenant_id', true)::integer)"
        )
        cursor.execute(
            f"""
            CREATE FUNCTION {schema}.guard_secure_item()
            RETURNS trigger
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog
            AS $function$
            BEGIN
              IF NEW.label IS NULL THEN
                RAISE EXCEPTION 'label is required';
              END IF;
              RETURN NEW;
            END;
            $function$
            """
        )
        cursor.execute(f"REVOKE ALL ON FUNCTION {schema}.guard_secure_item() FROM PUBLIC")
        cursor.execute(
            f"CREATE TRIGGER secure_items_guard BEFORE INSERT OR UPDATE "
            f"ON {schema}.secure_items FOR EACH ROW "
            f"EXECUTE FUNCTION {schema}.guard_secure_item()"
        )
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP SCHEMA {schema} CASCADE")


def _report(parameters: dict[str, object], contract: dict[str, object]) -> dict[str, object]:
    import psycopg

    with psycopg.connect(**parameters) as inspection:
        return build_report(contract, read_catalog(inspection))


def _fixture_definition_sha256(parameters: dict[str, object], signature: str) -> str:
    import psycopg

    with psycopg.connect(**parameters) as inspection:
        catalog = read_catalog(inspection)
    definition = next(
        row["definition"] for row in catalog["functions"] if row["signature"] == signature
    )
    normalized = _normalize_sql(definition)
    assert normalized is not None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _missing_kinds(report: dict[str, object]) -> set[str]:
    return {item["kind"] for item in report["missing"]}


def test_real_catalog_detects_policy_check_trigger_and_search_path_drift() -> None:
    import psycopg

    parameters = _connection_parameters()
    schema = f"parity_auth_{uuid4().hex}"
    with psycopg.connect(**parameters, autocommit=True) as owner:
        with owner.cursor() as cursor:
            cursor.execute("SELECT current_user")
            owner_name = str(cursor.fetchone()[0])
        with _fixture_schema(owner, schema):
            signature = f"{schema}.guard_secure_item()"
            contract = _contract(
                schema,
                owner_name,
                _fixture_definition_sha256(parameters, signature),
            )
            assert _report(parameters, contract)["status"] == "present"

            with owner.cursor() as cursor:
                cursor.execute(f"DROP POLICY secure_items_select ON {schema}.secure_items")
            report = _report(parameters, contract)
            assert "policy" in _missing_kinds(report)
            assert "policy_set" in _missing_kinds(report)

            with owner.cursor() as cursor:
                cursor.execute(
                    f"CREATE POLICY secure_items_select ON {schema}.secure_items "
                    "FOR SELECT TO PUBLIC USING (true)"
                )
            assert "policy" in _missing_kinds(_report(parameters, contract))

            with owner.cursor() as cursor:
                cursor.execute(f"DROP POLICY secure_items_select ON {schema}.secure_items")
                cursor.execute(
                    f"CREATE POLICY secure_items_select ON {schema}.secure_items "
                    "FOR SELECT TO PUBLIC USING ("
                    "tenant_id = current_setting('app.tenant_id', true)::integer)"
                )
                cursor.execute(
                    f"ALTER TABLE {schema}.secure_items " "DROP CONSTRAINT secure_items_label_check"
                )
                cursor.execute(
                    f"ALTER TABLE {schema}.secure_items ADD CONSTRAINT "
                    "secure_items_label_check CHECK (true)"
                )
            assert "constraint" in _missing_kinds(_report(parameters, contract))

            with owner.cursor() as cursor:
                cursor.execute(
                    f"ALTER TABLE {schema}.secure_items " "DROP CONSTRAINT secure_items_label_check"
                )
                cursor.execute(
                    f"ALTER TABLE {schema}.secure_items ADD CONSTRAINT "
                    "secure_items_label_check "
                    "CHECK (label = ANY (ARRAY['pending'::text, 'complete'::text]))"
                )
                cursor.execute(
                    f"ALTER TABLE {schema}.secure_items DISABLE TRIGGER secure_items_guard"
                )
            assert "trigger" in _missing_kinds(_report(parameters, contract))

            with owner.cursor() as cursor:
                cursor.execute(
                    f"ALTER TABLE {schema}.secure_items ENABLE TRIGGER secure_items_guard"
                )
                cursor.execute(f"ALTER FUNCTION {schema}.guard_secure_item() RESET search_path")
            assert "function" in _missing_kinds(_report(parameters, contract))
