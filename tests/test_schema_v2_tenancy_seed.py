from __future__ import annotations

import dataclasses
import unittest
from dataclasses import replace
from typing import Any
from uuid import uuid4

from geo_core.bootstrap import build_project_bootstrap
from geo_core.repositories.schema_v2_tenancy_repository import (
    PrivilegedSchemaV2TenancyRepository,
    SchemaV2TenancySeedConflictError,
)
from geo_core.schema_v2.tenancy_seed import (
    CanonicalJsonObject,
    SchemaV2TenancySeed,
    SchemaV2TenancySeedValidationError,
    translate_project_bootstrap_to_v2_seed,
    validate_v2_tenancy_seed,
)


def bootstrap(*, owner_user_id: str = " Owner@Example.COM ") -> Any:
    return build_project_bootstrap(
        tenant_name="Seed Tenant",
        project_name="Seed Project",
        target_brand="Seed Brand",
        category="Seed Category",
        market_code="AU",
        market_name="Australia",
        locale="en-AU",
        timezone="Australia/Sydney",
        currency="AUD",
        primary_language="English",
        industry_code="home_goods",
        industry_name="Home Goods",
        competitors=("Competitor One",),
        owner_user_id=owner_user_id,
    )


class FakeCursor:
    def __init__(
        self,
        *,
        insert_results: list[object] | None = None,
        select_results: list[list[tuple[object, ...]]] | None = None,
        fail_on: str | None = None,
    ) -> None:
        self.insert_results = list(insert_results or [])
        self.select_results = list(select_results or [])
        self.fail_on = fail_on
        self.statements: list[str] = []
        self.parameters: list[tuple[object, ...]] = []
        self.last_operation = ""

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        return None

    def execute(self, statement: str, params: tuple[object, ...] = ()) -> None:
        normalized = " ".join(statement.split())
        self.statements.append(normalized)
        self.parameters.append(params)
        if self.fail_on and self.fail_on in normalized:
            raise RuntimeError("simulated database failure")
        self.last_operation = "insert" if normalized.startswith("INSERT") else "select"

    def fetchone(self) -> object:
        if self.last_operation != "insert":
            raise AssertionError("fetchone is only expected after an insert")
        if not self.insert_results:
            raise AssertionError("missing fake insert result")
        return self.insert_results.pop(0)

    def fetchall(self) -> list[tuple[object, ...]]:
        if self.last_operation != "select":
            raise AssertionError("fetchall is only expected after a select")
        if not self.select_results:
            raise AssertionError("missing fake select result")
        return self.select_results.pop(0)


class FakeConnection:
    def __init__(self, cursor: FakeCursor, *, autocommit: bool = False) -> None:
        self.cursor_instance = cursor
        self.autocommit = autocommit
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


def persisted_rows(seed: SchemaV2TenancySeed) -> list[tuple[object, ...]]:
    market = seed.market_profile
    industry = seed.industry_profile
    tenant = seed.tenant
    project = seed.project
    rows: list[tuple[object, ...]] = [
        (market.id, market.market_code, market.payload.to_dict()),
        (
            industry.id,
            industry.market_code,
            industry.industry_code,
            industry.payload.to_dict(),
        ),
        (tenant.id, tenant.name, tenant.slug, tenant.status),
        (
            project.id,
            project.tenant_id,
            project.name,
            project.market_code,
            project.industry_code,
            project.target_brand,
            project.category,
            project.prompt_version,
            project.status,
        ),
    ]
    rows.extend(
        (
            member.id,
            member.tenant_id,
            member.project_id,
            member.user_id,
            member.role,
            member.status,
            member.invited_by,
        )
        for member in seed.project_members
    )
    rows.extend(
        (
            event.id,
            event.tenant_id,
            event.project_id,
            event.event_type,
            event.actor_type,
            event.actor_id,
            event.target_type,
            event.target_id,
            event.before_hash,
            event.after_hash,
            event.input_refs.to_dict(),
            event.output_refs.to_dict(),
            event.method_version,
            event.reason,
        )
        for event in seed.audit_events
    )
    return rows


class SchemaV2TenancyTranslatorTest(unittest.TestCase):
    def test_translation_canonicalizes_and_derives_project_scope(self) -> None:
        seed = translate_project_bootstrap_to_v2_seed(bootstrap())

        self.assertEqual(seed.tenant.status, "active")
        self.assertEqual(seed.project.status, "paused")
        self.assertEqual(seed.project.tenant_id, seed.tenant.id)
        self.assertEqual(seed.project_members[0].tenant_id, seed.tenant.id)
        self.assertEqual(seed.project_members[0].project_id, seed.project.id)
        self.assertEqual(seed.project_members[0].user_id, "owner@example.com")
        self.assertEqual(seed.project_members[0].role, "project_owner")
        self.assertEqual(seed.audit_events[0].tenant_id, seed.tenant.id)
        self.assertEqual(seed.audit_events[0].project_id, seed.project.id)
        self.assertEqual(seed.audit_events[0].actor_id, seed.project_members[0].user_id)
        self.assertEqual(seed.market_profile.payload.to_dict()["market_code"], "AU")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            seed.tenant.status = "disabled"  # type: ignore[misc]

    def test_role_translation_is_explicit_and_unknown_roles_fail_closed(self) -> None:
        source = bootstrap()
        expected = {
            "owner": "project_owner",
            "admin": "project_owner",
            "analyst": "analyst",
            "viewer": "client_viewer",
        }
        for source_role, target_role in expected.items():
            with self.subTest(source_role=source_role):
                member = replace(source.members[0], role=source_role)
                members = (member,)
                translated_index = 0
                if target_role != "project_owner":
                    member = replace(
                        member,
                        id=str(uuid4()),
                        user_id=f"{source_role}@example.com",
                    )
                    members = (source.members[0], member)
                    translated_index = 1
                translated = translate_project_bootstrap_to_v2_seed(
                    replace(source, members=members)
                )
                self.assertEqual(translated.project_members[translated_index].role, target_role)

        invalid_member = replace(
            source.members[0],
            id=str(uuid4()),
            user_id="invalid@example.com",
            role="billing_admin",
        )
        with self.assertRaises(SchemaV2TenancySeedValidationError) as raised:
            translate_project_bootstrap_to_v2_seed(
                replace(source, members=(source.members[0], invalid_member))
            )
        self.assertEqual(raised.exception.code, "unsupported_role")

    def test_statuses_must_be_supported_by_sealed_0010(self) -> None:
        source = bootstrap()
        active_project = replace(source.project, status="active")
        translated = translate_project_bootstrap_to_v2_seed(
            replace(source, project=active_project),
            tenant_status="disabled",
        )
        self.assertEqual(translated.tenant.status, "disabled")
        self.assertEqual(translated.project.status, "active")

        invalid_project = replace(source.project, status="publishing")
        with self.assertRaises(SchemaV2TenancySeedValidationError) as raised:
            translate_project_bootstrap_to_v2_seed(replace(source, project=invalid_project))
        self.assertEqual(raised.exception.field, "project.status")

    def test_validator_rejects_cross_tenant_member_and_audit_references(self) -> None:
        seed = translate_project_bootstrap_to_v2_seed(bootstrap())
        invalid_member = replace(seed.project_members[0], tenant_id=uuid4())
        with self.assertRaises(SchemaV2TenancySeedValidationError) as member_error:
            validate_v2_tenancy_seed(replace(seed, project_members=(invalid_member,)))
        self.assertEqual(member_error.exception.code, "scope_mismatch")

        invalid_audit = replace(seed.audit_events[0], tenant_id=uuid4())
        with self.assertRaises(SchemaV2TenancySeedValidationError) as audit_error:
            validate_v2_tenancy_seed(replace(seed, audit_events=(invalid_audit,)))
        self.assertEqual(audit_error.exception.code, "scope_mismatch")

    def test_translator_does_not_silently_repair_legacy_scope_mismatches(self) -> None:
        source = bootstrap()
        bad_member = replace(source.members[0], project_id=str(uuid4()))
        with self.assertRaises(SchemaV2TenancySeedValidationError) as member_error:
            translate_project_bootstrap_to_v2_seed(replace(source, members=(bad_member,)))
        self.assertEqual(member_error.exception.code, "scope_mismatch")

        bad_audit = replace(source.audit_events[0], project_id=str(uuid4()))
        with self.assertRaises(SchemaV2TenancySeedValidationError) as audit_error:
            translate_project_bootstrap_to_v2_seed(replace(source, audit_events=(bad_audit,)))
        self.assertEqual(audit_error.exception.code, "scope_mismatch")

    def test_validator_rejects_noncanonical_direct_dto_values(self) -> None:
        seed = translate_project_bootstrap_to_v2_seed(bootstrap())
        invalid_project = replace(seed.project, status=" PAUSED ")
        with self.assertRaises(SchemaV2TenancySeedValidationError) as raised:
            validate_v2_tenancy_seed(replace(seed, project=invalid_project))
        self.assertEqual(raised.exception.code, "noncanonical_value")

    def test_independent_rebuilds_share_canonical_identity_and_audit_lineage(self) -> None:
        first = translate_project_bootstrap_to_v2_seed(
            bootstrap(owner_user_id=" Owner@Example.COM ")
        )
        second = translate_project_bootstrap_to_v2_seed(
            bootstrap(owner_user_id="owner@example.com")
        )

        self.assertEqual(first, second)
        self.assertEqual(first.project_members[0].id, second.project_members[0].id)
        self.assertEqual(first.project_members[0].user_id, "owner@example.com")
        self.assertEqual(first.audit_events[0].actor_id, "owner@example.com")
        self.assertEqual(first.audit_events[0].input_refs.to_dict(), {})
        self.assertEqual(
            set(first.audit_events[0].output_refs.to_dict()),
            {"competitor_entity_ids"},
        )

    def test_validator_requires_exact_frozen_dto_graph(self) -> None:
        seed = translate_project_bootstrap_to_v2_seed(bootstrap())
        invalid_values = (
            (object(), "seed"),
            (replace(seed, tenant=object()), "tenant"),  # type: ignore[arg-type]
            (
                replace(seed, project_members=list(seed.project_members)),  # type: ignore[arg-type]
                "project_members",
            ),
            (
                replace(seed, audit_events=list(seed.audit_events)),  # type: ignore[arg-type]
                "audit_events",
            ),
            (
                replace(seed, project_members=(object(),)),  # type: ignore[arg-type]
                "project_members[0]",
            ),
        )
        for invalid_seed, expected_field in invalid_values:
            with self.subTest(expected_field=expected_field):
                with self.assertRaises(SchemaV2TenancySeedValidationError) as raised:
                    validate_v2_tenancy_seed(invalid_seed)  # type: ignore[arg-type]
                self.assertEqual(raised.exception.code, "invalid_dto_type")
                self.assertEqual(raised.exception.field, expected_field)

    def test_validator_requires_an_active_project_owner(self) -> None:
        seed = translate_project_bootstrap_to_v2_seed(bootstrap())
        analyst = replace(seed.project_members[0], role="analyst")
        with self.assertRaises(SchemaV2TenancySeedValidationError) as raised:
            validate_v2_tenancy_seed(replace(seed, project_members=(analyst,)))
        self.assertEqual(raised.exception.code, "missing_active_project_owner")

        disabled_owner = replace(seed.project_members[0], status="disabled")
        with self.assertRaises(SchemaV2TenancySeedValidationError) as disabled_error:
            validate_v2_tenancy_seed(replace(seed, project_members=(disabled_owner,)))
        self.assertEqual(disabled_error.exception.code, "missing_active_project_owner")

    def test_validator_requires_member_id_from_canonical_identity(self) -> None:
        seed = translate_project_bootstrap_to_v2_seed(bootstrap())
        invalid_member = replace(seed.project_members[0], id=uuid4())
        with self.assertRaises(SchemaV2TenancySeedValidationError) as raised:
            validate_v2_tenancy_seed(replace(seed, project_members=(invalid_member,)))
        self.assertEqual(raised.exception.code, "noncanonical_member_id")

    def test_bootstrap_audit_contract_rejects_secrets_and_broken_lineage(self) -> None:
        source = bootstrap()
        invalid_events = (
            (
                replace(source.audit_events[0], input_refs={"session_token": ["raw"]}),
                "sensitive_audit_ref",
            ),
            (
                replace(source.audit_events[0], output_refs={"password_hash": ["raw"]}),
                "sensitive_audit_ref",
            ),
            (
                replace(source.audit_events[0], output_refs={"other_ids": [str(uuid4())]}),
                "unsupported_audit_ref",
            ),
            (
                replace(
                    source.audit_events[0],
                    output_refs={"competitor_entity_ids": ["not-a-uuid"]},
                ),
                "invalid_uuid",
            ),
            (
                replace(source.audit_events[0], target_id=str(uuid4())),
                "audit_target_mismatch",
            ),
            (
                replace(source.audit_events[0], actor_id="other@example.com"),
                "audit_actor_not_member",
            ),
        )
        for event, expected_code in invalid_events:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(SchemaV2TenancySeedValidationError) as raised:
                    translate_project_bootstrap_to_v2_seed(
                        replace(source, audit_events=(event,))
                    )
                self.assertEqual(raised.exception.code, expected_code)

    def test_validator_covers_all_direct_dto_database_fields(self) -> None:
        seed = translate_project_bootstrap_to_v2_seed(bootstrap())
        invalid_seeds = (
            (
                replace(
                    seed,
                    market_profile=replace(seed.market_profile, payload={}),  # type: ignore[arg-type]
                ),
                "market_profile.payload",
            ),
            (
                replace(
                    seed,
                    industry_profile=replace(seed.industry_profile, industry_code=" "),
                ),
                "industry_profile.industry_code",
            ),
            (replace(seed, tenant=replace(seed.tenant, name=" ")), "tenant.name"),
            (replace(seed, project=replace(seed.project, name=" ")), "project.name"),
            (
                replace(seed, project=replace(seed.project, target_brand=" ")),
                "project.target_brand",
            ),
            (replace(seed, project=replace(seed.project, category=" ")), "project.category"),
            (
                replace(seed, project=replace(seed.project, prompt_version=" ")),
                "project.prompt_version",
            ),
            (
                replace(
                    seed,
                    project_members=(replace(seed.project_members[0], status=" DISABLED "),),
                ),
                "project_members[0].status",
            ),
            (
                replace(seed, audit_events=(replace(seed.audit_events[0], event_type=" "),)),
                "audit_events[0].event_type",
            ),
            (
                replace(
                    seed,
                    audit_events=(
                        replace(seed.audit_events[0], input_refs={}),  # type: ignore[arg-type]
                    ),
                ),
                "audit_events[0].input_refs",
            ),
            (
                replace(
                    seed,
                    audit_events=(replace(seed.audit_events[0], method_version=" "),),
                ),
                "audit_events[0].method_version",
            ),
            (replace(seed, project_members=()), "project_members"),
            (replace(seed, audit_events=()), "audit_events"),
        )
        for invalid_seed, expected_field in invalid_seeds:
            with self.subTest(expected_field=expected_field):
                with self.assertRaises(SchemaV2TenancySeedValidationError) as raised:
                    validate_v2_tenancy_seed(invalid_seed)
                self.assertEqual(raised.exception.field, expected_field)

    def test_canonical_json_object_rejects_mutable_or_noncanonical_construction(self) -> None:
        value = CanonicalJsonObject.from_value({"items": [{"name": "one"}]})
        mutable_copy = value.to_dict()
        mutable_copy["items"][0]["name"] = "changed"
        self.assertEqual(value.to_dict(), {"items": [{"name": "one"}]})
        with self.assertRaises(ValueError):
            CanonicalJsonObject('{"z": 1, "a": 2}')


class SchemaV2TenancyRepositoryTest(unittest.TestCase):
    def test_fresh_seed_uses_dependency_order_and_one_commit(self) -> None:
        seed = translate_project_bootstrap_to_v2_seed(bootstrap())
        entity_count = 4 + len(seed.project_members) + len(seed.audit_events)
        cursor = FakeCursor(insert_results=[(1,)] * entity_count)
        connection = FakeConnection(cursor)

        PrivilegedSchemaV2TenancyRepository(connection).save(seed)

        insert_tables = [
            statement.split("INSERT INTO public.", 1)[1].split(" ", 1)[0]
            for statement in cursor.statements
        ]
        self.assertEqual(
            insert_tables,
            [
                "market_profiles",
                "industry_profiles",
                "tenants",
                "projects",
                "project_members",
                "audit_events",
            ],
        )
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        sql = "\n".join(cursor.statements).upper()
        self.assertNotIn("CREATED_AT", sql)
        self.assertNotIn("UPDATE PUBLIC.AUDIT_EVENTS", sql)
        self.assertNotIn("SET ROLE", sql)
        self.assertNotIn("SET_CONFIG", sql)
        self.assertNotIn("APP.", sql)

    def test_independently_rebuilt_seed_is_idempotent_without_updates(self) -> None:
        first_seed = translate_project_bootstrap_to_v2_seed(
            bootstrap(owner_user_id="Owner@Example.com")
        )
        replay_seed = translate_project_bootstrap_to_v2_seed(
            bootstrap(owner_user_id="owner@example.COM")
        )
        rows = persisted_rows(first_seed)
        cursor = FakeCursor(
            insert_results=[None] * len(rows),
            select_results=[[row] for row in rows],
        )
        connection = FakeConnection(cursor)

        PrivilegedSchemaV2TenancyRepository(connection).save(replay_seed)

        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        self.assertEqual(cursor.insert_results, [])
        self.assertEqual(cursor.select_results, [])
        self.assertFalse(any(statement.startswith("UPDATE") for statement in cursor.statements))

    def test_existing_member_role_or_status_conflict_rolls_back(self) -> None:
        seed = translate_project_bootstrap_to_v2_seed(bootstrap())
        member_row = list(persisted_rows(seed)[4])
        member_row[4] = "client_viewer"
        member_row[5] = "disabled"
        cursor = FakeCursor(
            insert_results=[(1,), (1,), (1,), (1,), None],
            select_results=[[tuple(member_row)]],
        )
        connection = FakeConnection(cursor)

        with self.assertRaises(SchemaV2TenancySeedConflictError) as raised:
            PrivilegedSchemaV2TenancyRepository(connection).save(seed)

        self.assertEqual(raised.exception.entity, "project_member")
        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 1)
        self.assertFalse(any("audit_events" in statement for statement in cursor.statements))

    def test_existing_profile_payload_conflict_rolls_back(self) -> None:
        seed = translate_project_bootstrap_to_v2_seed(bootstrap())
        market_row = list(persisted_rows(seed)[0])
        market_row[2] = {"market_code": "NZ"}
        cursor = FakeCursor(insert_results=[None], select_results=[[tuple(market_row)]])
        connection = FakeConnection(cursor)

        with self.assertRaises(SchemaV2TenancySeedConflictError) as raised:
            PrivilegedSchemaV2TenancyRepository(connection).save(seed)

        self.assertEqual(raised.exception.entity, "market_profile")
        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 1)

    def test_existing_project_status_conflict_rolls_back(self) -> None:
        seed = translate_project_bootstrap_to_v2_seed(bootstrap())
        project_row = list(persisted_rows(seed)[3])
        project_row[8] = "active"
        cursor = FakeCursor(
            insert_results=[(1,), (1,), (1,), None],
            select_results=[[tuple(project_row)]],
        )
        connection = FakeConnection(cursor)

        with self.assertRaises(SchemaV2TenancySeedConflictError) as raised:
            PrivilegedSchemaV2TenancyRepository(connection).save(seed)

        self.assertEqual(raised.exception.entity, "project")
        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 1)

    def test_database_exception_rolls_back_without_commit(self) -> None:
        seed = translate_project_bootstrap_to_v2_seed(bootstrap())
        cursor = FakeCursor(
            insert_results=[(1,), (1,), (1,)],
            fail_on="INSERT INTO public.projects",
        )
        connection = FakeConnection(cursor)

        with self.assertRaisesRegex(RuntimeError, "simulated database failure"):
            PrivilegedSchemaV2TenancyRepository(connection).save(seed)

        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 1)

    def test_autocommit_connection_is_rejected(self) -> None:
        connection = FakeConnection(FakeCursor(), autocommit=True)
        with self.assertRaisesRegex(ValueError, "autocommit"):
            PrivilegedSchemaV2TenancyRepository(connection)


if __name__ == "__main__":
    unittest.main()
