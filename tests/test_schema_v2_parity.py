from __future__ import annotations

import copy
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.verify_schema_v2_parity import (
    ParityVerifierError,
    _parser,
    build_report,
    main,
    render_report,
    validate_contract,
)


def _contract() -> dict[str, object]:
    return {
        "contract_version": 2,
        "schema_generation": 2,
        "domain": "auth",
        "database_name": "geno_v2",
        "source_parity": {"mappings": []},
        "v2_hardening": {"deviations": []},
        "connection_identity": {"must_not_equal_roles": ["runtime_app", "authz_owner"]},
        "roles": [
            {
                "name": "runtime_app",
                "login": False,
                "superuser": False,
                "create_database": False,
                "create_role": False,
                "replication": False,
                "bypass_rls": False,
                "member_of": [],
            },
            {
                "name": "authz_owner",
                "login": False,
                "superuser": False,
                "create_database": False,
                "create_role": False,
                "replication": False,
                "bypass_rls": True,
                "member_of": [],
            },
        ],
        "tables": [
            {
                "name": "public.secure_items",
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
                        "name": "secure_items_tenant_fkey",
                        "category": "foreign_key",
                        "columns": ["tenant_id"],
                        "references": {"table": "public.tenants", "columns": ["id"]},
                        "on_update": "a",
                        "on_delete": "c",
                        "validated": True,
                    },
                    {
                        "name": "secure_items_label_check",
                        "category": "check",
                        "validated": True,
                        "expression": {
                            "required": ["label = any", "pending", "complete"],
                            "forbidden": ["false"],
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
                        "predicate": {"required": ["label <> 'deleted'::text"]},
                    }
                ],
                "rls": {"enabled": True, "forced": True},
                "policies": [
                    {
                        "name": "secure_items_select",
                        "command": "select",
                        "permissive": True,
                        "roles": ["runtime_app"],
                        "using": {
                            "required": ["tenant_id", "current_setting('app.tenant_id'::text)"],
                            "forbidden": [],
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
                        "function": "public.guard_secure_item()",
                    }
                ],
                "acl": {"PUBLIC": [], "runtime_app": ["SELECT"]},
                "column_acl": {
                    "runtime_app": {"label": ["UPDATE"]},
                },
            }
        ],
        "functions": [
            {
                "signature": "public.guard_secure_item()",
                "kind": "function",
                "owner": "authz_owner",
                "return_type": "trigger",
                "language": "plpgsql",
                "security_definer": True,
                "volatility": "volatile",
                "settings": ["search_path=pg_catalog"],
                "execute_roles": ["authz_owner"],
                "definition": {
                    "required": ["raise exception", "return new"],
                    "forbidden": ["execute format"],
                },
            }
        ],
    }


def _catalog() -> dict[str, object]:
    return {
        "database_name": "geno_v2",
        "current_user": "schema_installer",
        "roles": [
            {
                "name": "runtime_app",
                "login": False,
                "superuser": False,
                "create_database": False,
                "create_role": False,
                "replication": False,
                "bypass_rls": False,
            },
            {
                "name": "authz_owner",
                "login": False,
                "superuser": False,
                "create_database": False,
                "create_role": False,
                "replication": False,
                "bypass_rls": True,
            },
        ],
        "role_memberships": [],
        "tables": [{"name": "public.secure_items", "rls_enabled": True, "rls_forced": True}],
        "columns": [
            {
                "table_name": "public.secure_items",
                "name": "id",
                "type": "integer",
                "not_null": True,
                "default_expression": None,
            },
            {
                "table_name": "public.secure_items",
                "name": "tenant_id",
                "type": "integer",
                "not_null": True,
                "default_expression": None,
            },
            {
                "table_name": "public.secure_items",
                "name": "label",
                "type": "text",
                "not_null": True,
                "default_expression": "'pending'::text",
            },
        ],
        "constraints": [
            {
                "table_name": "public.secure_items",
                "name": "secure_items_pkey",
                "type": "p",
                "validated": True,
                "deferrable": False,
                "initially_deferred": False,
                "on_update": " ",
                "on_delete": " ",
                "columns": ["id"],
                "referenced_table": None,
                "referenced_columns": [],
                "expression": None,
            },
            {
                "table_name": "public.secure_items",
                "name": "secure_items_tenant_fkey",
                "type": "f",
                "validated": True,
                "deferrable": False,
                "initially_deferred": False,
                "on_update": "a",
                "on_delete": "c",
                "columns": ["tenant_id"],
                "referenced_table": "public.tenants",
                "referenced_columns": ["id"],
                "expression": None,
            },
            {
                "table_name": "public.secure_items",
                "name": "secure_items_label_check",
                "type": "c",
                "validated": True,
                "deferrable": False,
                "initially_deferred": False,
                "on_update": " ",
                "on_delete": " ",
                "columns": ["label"],
                "referenced_table": None,
                "referenced_columns": [],
                "expression": "label = ANY (ARRAY['pending'::text, 'complete'::text])",
            },
        ],
        "indexes": [
            {
                "table_name": "public.secure_items",
                "name": "secure_items_label_unique",
                "unique": True,
                "valid": True,
                "ready": True,
                "keys": ["tenant_id", "lower(label)"],
                "predicate": "label <> 'deleted'::text",
            }
        ],
        "policies": [
            {
                "table_name": "public.secure_items",
                "name": "secure_items_select",
                "command": "select",
                "permissive": True,
                "roles": ["runtime_app"],
                "using_expression": "tenant_id = current_setting('app.tenant_id'::text)::integer",
                "with_check_expression": None,
            }
        ],
        "triggers": [
            {
                "table_name": "public.secure_items",
                "name": "secure_items_guard",
                "timing": "before",
                "events": ["insert", "update"],
                "row_level": True,
                "enabled": "O",
                "function_signature": "public.guard_secure_item()",
            }
        ],
        "table_acl": [
            {
                "table_name": "public.secure_items",
                "grantee": "runtime_app",
                "privilege_type": "SELECT",
            }
        ],
        "column_acl": [
            {
                "table_name": "public.secure_items",
                "column_name": "label",
                "grantee": "runtime_app",
                "privilege_type": "UPDATE",
            }
        ],
        "functions": [
            {
                "signature": "public.guard_secure_item()",
                "kind": "function",
                "owner": "authz_owner",
                "return_type": "trigger",
                "language": "plpgsql",
                "security_definer": True,
                "volatility": "volatile",
                "settings": ["search_path=pg_catalog"],
                "definition": "CREATE FUNCTION public.guard_secure_item() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'blocked'; RETURN NEW; END $$",
            }
        ],
        "function_acl": [
            {"signature": "public.guard_secure_item()", "grantee": "authz_owner"}
        ],
    }


def _missing_requirements(report: dict[str, object]) -> set[tuple[str, str]]:
    return {(item["kind"], item["name"]) for item in report["missing"]}


def test_independent_fixture_contract_is_valid_and_complete() -> None:
    contract = _contract()
    validate_contract(contract, domain="auth")

    report = build_report(contract, _catalog())

    assert report["status"] == "present"
    assert report["missing"] == []
    assert report["summary"]["expected"] == report["summary"]["present"]


def test_report_is_deterministic_for_reordered_catalog_rows() -> None:
    catalog = _catalog()
    reversed_catalog = {
        key: list(reversed(value)) if isinstance(value, list) else value
        for key, value in catalog.items()
    }

    assert render_report(build_report(_contract(), catalog)) == render_report(
        build_report(_contract(), reversed_catalog)
    )


@pytest.mark.parametrize(
    ("mutate", "expected_kind", "expected_name"),
    [
        (
            lambda catalog: catalog["columns"][2].update(default_expression="'open'::text"),
            "column",
            "public.secure_items.label",
        ),
        (
            lambda catalog: catalog["constraints"][1].update(on_delete="a"),
            "constraint",
            "public.secure_items.secure_items_tenant_fkey",
        ),
        (
            lambda catalog: catalog["constraints"][2].update(expression="true"),
            "constraint",
            "public.secure_items.secure_items_label_check",
        ),
        (
            lambda catalog: catalog["constraints"][2].update(validated=False),
            "constraint",
            "public.secure_items.secure_items_label_check",
        ),
        (
            lambda catalog: catalog["indexes"][0].update(keys=["tenant_id", "label"]),
            "index",
            "public.secure_items.secure_items_label_unique",
        ),
        (
            lambda catalog: catalog["indexes"][0].update(predicate="false"),
            "index",
            "public.secure_items.secure_items_label_unique",
        ),
        (
            lambda catalog: catalog["policies"][0].update(using_expression="true"),
            "policy",
            "public.secure_items.secure_items_select",
        ),
        (
            lambda catalog: catalog["policies"][0].update(roles=["PUBLIC"]),
            "policy",
            "public.secure_items.secure_items_select",
        ),
        (
            lambda catalog: catalog["triggers"][0].update(enabled="D"),
            "trigger",
            "public.secure_items.secure_items_guard",
        ),
        (
            lambda catalog: catalog["triggers"][0].update(events=["update"]),
            "trigger",
            "public.secure_items.secure_items_guard",
        ),
        (
            lambda catalog: catalog["functions"][0].update(owner="runtime_app"),
            "function",
            "public.guard_secure_item()",
        ),
        (
            lambda catalog: catalog["functions"][0].update(settings=[]),
            "function",
            "public.guard_secure_item()",
        ),
        (
            lambda catalog: catalog["functions"][0].update(definition="RETURN NEW"),
            "function",
            "public.guard_secure_item()",
        ),
        (
            lambda catalog: catalog.update(function_acl=[]),
            "function_acl",
            "public.guard_secure_item()",
        ),
        (
            lambda catalog: catalog["table_acl"].append(
                {
                    "table_name": "public.secure_items",
                    "grantee": "PUBLIC",
                    "privilege_type": "SELECT",
                }
            ),
            "table_acl",
            "public.secure_items:PUBLIC",
        ),
        (
            lambda catalog: catalog["role_memberships"].append(
                {"member_name": "runtime_app", "role_name": "authz_owner"}
            ),
            "role_membership",
            "runtime_app",
        ),
    ],
)
def test_security_relevant_catalog_drift_is_missing(
    mutate: object,
    expected_kind: str,
    expected_name: str,
) -> None:
    catalog = copy.deepcopy(_catalog())
    mutate(catalog)

    report = build_report(_contract(), catalog)

    assert report["status"] == "missing"
    assert (expected_kind, expected_name) in _missing_requirements(report)


def test_deleting_policy_or_trigger_fails_the_exact_set_contract() -> None:
    for collection, expected_kind in (("policies", "policy_set"), ("triggers", "trigger_set")):
        catalog = copy.deepcopy(_catalog())
        catalog[collection] = []

        report = build_report(_contract(), catalog)

        assert (expected_kind, "public.secure_items") in _missing_requirements(report)


def test_cli_writes_missing_report_and_returns_one() -> None:
    catalog = copy.deepcopy(_catalog())
    catalog["policies"] = []
    fake_connection = SimpleNamespace(close=lambda: None)
    with tempfile.TemporaryDirectory() as temp_dir:
        contract_path = Path(temp_dir) / "auth.json"
        contract_path.write_text(json.dumps(_contract()), encoding="utf-8")
        report_path = Path(temp_dir) / "report.json"
        with (
            patch("scripts.verify_schema_v2_parity._connect", return_value=fake_connection),
            patch("scripts.verify_schema_v2_parity.read_catalog", return_value=catalog),
        ):
            exit_code = main(
                [
                    "--domain",
                    "auth",
                    "--contract-root",
                    temp_dir,
                    "--report-json",
                    str(report_path),
                ]
            )
        report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["status"] == "missing"


def test_cli_has_no_database_url_argument() -> None:
    help_text = _parser().format_help()

    assert "--database-url" not in help_text
    assert "PGHOST" not in help_text


def test_structured_pg_connection_failure_never_renders_credentials() -> None:
    secret = "PGPASSWORD_SECRET"

    def fail_connect(*args: object, **kwargs: object) -> object:
        raise RuntimeError(f"driver included connection data: {args!r} {kwargs!r}")

    environment = {
        "PGHOST": "db.internal",
        "PGPORT": "5432",
        "PGDATABASE": "geno_v2",
        "PGUSER": "schema_verifier",
        "PGPASSWORD": secret,
    }
    stderr = io.StringIO()
    stdout = io.StringIO()
    with (
        patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=fail_connect)}),
        patch.dict(os.environ, environment, clear=True),
        patch("scripts.verify_schema_v2_parity.load_contract", return_value=_contract()),
        patch("sys.stderr", stderr),
        patch("sys.stdout", stdout),
    ):
        exit_code = main(["--domain", "auth"])

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "schema-v2 parity error: database connection failed\n"
    assert secret not in stderr.getvalue()


def test_contract_rejects_missing_source_or_hardening_mapping() -> None:
    for key in ("source_parity", "v2_hardening"):
        contract = _contract()
        del contract[key]
        with pytest.raises(ParityVerifierError):
            validate_contract(contract, domain="auth")
