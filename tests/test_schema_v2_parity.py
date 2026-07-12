from __future__ import annotations

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
    CONSTRAINT_TYPES,
    ParityVerifierError,
    build_report,
    load_contract,
    main,
    render_report,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "infra/db/schema-v2/parity"


def _contract() -> dict[str, object]:
    return load_contract(CONTRACT_ROOT, "auth")


def _complete_fake_catalog(contract: dict[str, object]) -> dict[str, object]:
    role_rows = [dict(role) for role in contract["roles"]]  # type: ignore[index]
    table_rows: list[dict[str, object]] = []
    column_rows: list[dict[str, object]] = []
    constraint_rows: list[dict[str, object]] = []
    index_rows: list[dict[str, object]] = []
    for table in contract["tables"]:  # type: ignore[index]
        table_name = table["name"]
        table_rows.append(
            {
                "name": table_name,
                "rls_enabled": table["rls"]["enabled"],
                "rls_forced": table["rls"]["forced"],
            }
        )
        column_rows.extend(
            {"table_name": table_name, "name": column} for column in table["required_columns"]
        )
        for constraint in table["constraints"]:
            reference = constraint.get("references") or {}
            constraint_rows.append(
                {
                    "table_name": table_name,
                    "name": constraint["name"],
                    "type": CONSTRAINT_TYPES[constraint["category"]],
                    "columns": constraint.get("columns") or [],
                    "referenced_table": reference.get("table"),
                    "referenced_columns": reference.get("columns") or [],
                    "deferrable": constraint.get("deferrable", False),
                    "initially_deferred": constraint.get("initially_deferred", False),
                }
            )
        index_rows.extend(
            {
                "table_name": table_name,
                "name": index["name"],
                "unique": index["unique"],
                "partial": index["partial"],
            }
            for index in table.get("indexes", [])
        )
    function_rows = [dict(function) for function in contract["functions"]]  # type: ignore[index]
    return {
        "database_name": contract["database_name"],
        "roles": role_rows,
        "tables": table_rows,
        "columns": column_rows,
        "constraints": constraint_rows,
        "indexes": index_rows,
        "functions": function_rows,
    }


def test_auth_contract_names_the_tenancy_and_session_scope() -> None:
    contract = _contract()

    assert contract["database_name"] == "geno_v2"
    assert {role["name"] for role in contract["roles"]} == {
        "geno_v2_runtime",
        "geno_v2_authz_owner",
    }
    assert {table["name"] for table in contract["tables"]} == {
        "public.tenants",
        "public.projects",
        "public.tenant_members",
        "public.project_members",
        "public.project_member_invitations",
        "public.runtime_sessions",
        "public.runtime_project_access_grants",
        "public.auth_invitation_redemption_attempts",
    }
    categories = {
        constraint["category"]
        for table in contract["tables"]
        for constraint in table["constraints"]
    }
    assert "composite_foreign_key" in categories
    assert "deferrable_composite_foreign_key" in categories
    assert all(table["rls"] == {"enabled": True, "forced": True} for table in contract["tables"])


def test_fake_catalog_report_is_complete_and_order_independent() -> None:
    contract = _contract()
    catalog = _complete_fake_catalog(contract)

    first = build_report(contract, catalog)
    shuffled = {
        key: list(reversed(value)) if isinstance(value, list) else value
        for key, value in catalog.items()
    }
    second = build_report(contract, shuffled)

    assert first["status"] == "present"
    assert first["missing"] == []
    assert first["summary"]["expected"] == first["summary"]["present"]
    assert render_report(first) == render_report(second)


def test_fake_catalog_reports_missing_and_mismatched_requirements_deterministically() -> None:
    contract = _contract()
    catalog = _complete_fake_catalog(contract)
    catalog["roles"] = [row for row in catalog["roles"] if row["name"] != "geno_v2_runtime"]
    catalog["tables"] = [
        {**row, "rls_forced": False} if row["name"] == "public.projects" else row
        for row in catalog["tables"]
    ]
    catalog["functions"] = catalog["functions"][:-1]

    report = build_report(contract, catalog)
    missing = [(item["kind"], item["name"], item["requirement"]) for item in report["missing"]]

    assert report["status"] == "missing"
    assert missing == sorted(missing)
    assert ("role", "geno_v2_runtime", "object_and_attributes") in missing
    assert ("rls", "public.projects", "forced") in missing
    assert any(kind == "function" for kind, _name, _requirement in missing)


def test_cli_writes_missing_report_and_returns_one() -> None:
    empty_catalog = {
        "database_name": "geno_v2",
        "roles": [],
        "tables": [],
        "columns": [],
        "constraints": [],
        "indexes": [],
        "functions": [],
    }
    fake_connection = SimpleNamespace(close=lambda: None)
    with tempfile.TemporaryDirectory() as temp_dir:
        report_path = Path(temp_dir) / "auth-parity.json"
        with (
            patch("scripts.verify_schema_v2_parity._connect", return_value=fake_connection),
            patch("scripts.verify_schema_v2_parity.read_catalog", return_value=empty_catalog),
        ):
            exit_code = main(["--domain", "auth", "--report-json", str(report_path)])
        report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["status"] == "missing"
    assert report["summary"]["missing"] > 0


@pytest.mark.parametrize(
    ("arguments", "environment", "secret"),
    [
        (
            ["--domain", "auth", "--database-url", "postgresql://user:URL_SECRET@db/geno_v2"],
            {},
            "URL_SECRET",
        ),
        (
            ["--domain", "auth"],
            {
                "PGHOST": "db",
                "PGPORT": "5432",
                "PGDATABASE": "geno_v2",
                "PGUSER": "parity",
                "PGPASSWORD": "PGPASSWORD_SECRET",
            },
            "PGPASSWORD_SECRET",
        ),
    ],
)
def test_connection_failures_never_render_credentials(
    arguments: list[str],
    environment: dict[str, str],
    secret: str,
) -> None:
    def fail_connect(*args: object, **kwargs: object) -> object:
        raise RuntimeError(f"driver included secret connection data: {args!r} {kwargs!r}")

    stderr = io.StringIO()
    stdout = io.StringIO()
    with (
        patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=fail_connect)}),
        patch.dict(os.environ, environment, clear=True),
        patch("sys.stderr", stderr),
        patch("sys.stdout", stdout),
    ):
        exit_code = main(arguments)

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "schema-v2 parity error: database connection failed\n"
    assert secret not in stderr.getvalue()
    assert secret not in stdout.getvalue()


def test_contract_loader_rejects_unknown_domains_without_echoing_paths() -> None:
    with pytest.raises(ParityVerifierError, match="cannot load parity contract"):
        load_contract(CONTRACT_ROOT, "missing_domain")
