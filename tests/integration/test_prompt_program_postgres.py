from __future__ import annotations

import os
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.project_scope import set_project_scope
from geo_core.prompts.application import (
    PromptProgramApplication,
    PromptProgramForbidden,
    PromptProgramNotFound,
    PromptProgramRuntimeBlocked,
    PromptProgramVersionConflict,
)
from geo_core.prompts.postgres import build_prompt_program_api, prompt_program_uow_factory
from geo_core.prompts.program import (
    ModelPolicySnapshot,
    ProgramKind,
    ProgramSchemaContract,
    ProgramTestEvidence,
    PromptProgramRelease,
)
from tests.integration.placement_worker_support import (
    cleanup_projects,
    login_url,
    seed_project,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_prompt_program_history_replays_across_uow_and_resolves_exact_binding() -> None:
    suffix = uuid4().hex[:10]
    app_login, password = f"geo_prompt_program_{suffix}", uuid4().hex
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                sql.Identifier(app_login), sql.Literal(password)
            )
        )
        first = seed_project(admin, suffix=f"prompt-program-{suffix}-a")
        second = seed_project(admin, suffix=f"prompt-program-{suffix}-b")
    app_url = login_url(ADMIN_URL, user=app_login, password=password)
    factory = prompt_program_uow_factory(lambda: psycopg.connect(app_url))
    owner = _principal(first, "owner")
    reviewer = _principal(first, "reviewer")
    try:
        created = _command(
            factory,
            first["project"],
            lambda application: application.create_program(
                owner,
                project_id=first["project"],
                program_kind=ProgramKind.GENERATION,
                purpose="synthetic_lab.generation",
                system_template="Return Australian English for {{channel}}.",
                user_template="Write {{scenario}} for {{channel}}.",
                schemas=_schemas(),
                model_policy=_policy(),
                test_set_id=uuid4(),
                test_set_version=1,
                test_set_hash="ab" * 32,
                compiler_version="geo-prompt-compiler-v2",
                expected_version=0,
                idempotency_key="create:generation:v1",
            ),
        )
        replayed = _command(
            factory,
            first["project"],
            lambda application: application.create_program(
                owner,
                project_id=first["project"],
                program_kind=ProgramKind.GENERATION,
                purpose="synthetic_lab.generation",
                system_template="Return Australian English for {{channel}}.",
                user_template="Write {{scenario}} for {{channel}}.",
                schemas=_schemas(),
                model_policy=_policy(),
                test_set_id=created.value.release.test_set_id,
                test_set_version=1,
                test_set_hash=created.value.release.test_set_hash,
                compiler_version="geo-prompt-compiler-v2",
                expected_version=0,
                idempotency_key="create:generation:v1",
            ),
        )
        assert replayed.replayed is True
        assert replayed.value == created.value

        _assert_database_rejects_release_version_gap(
            app_url=app_url,
            project_id=first["project"],
            release_id=created.value.release.id,
        )
        _assert_database_rejects_evidence_actor_mismatch(
            app_url=app_url,
            project_id=first["project"],
            release=created.value.release,
            draft_state_id=created.value.state.id,
            state_actor=first["owner"],
            evidence_actor=first["reviewer"],
        )

        tested = _command(
            factory,
            first["project"],
            lambda application: application.record_test(
                owner,
                project_id=first["project"],
                release_id=created.value.release.id,
                output_artifact_ref="s3://prompt-tests/generation/fixed-run.json",
                output_hash="e" * 64,
                expected_version=1,
                idempotency_key="test:generation:v1",
            ),
        )
        with pytest.raises(PromptProgramForbidden, match="cannot approve"):
            _command(
                factory,
                first["project"],
                lambda application: application.approve_release(
                    owner,
                    project_id=first["project"],
                    release_id=created.value.release.id,
                    expected_version=2,
                    idempotency_key="approve:generation:owner",
                ),
            )
        _assert_database_rejects_owner_approval(
            app_url=app_url,
            project_id=first["project"],
            release_id=created.value.release.id,
            release_hash=created.value.release.release_hash,
            tested_state_id=tested.value.state.id,
            owner_id=first["owner"],
        )

        approved = _command(
            factory,
            first["project"],
            lambda application: application.approve_release(
                reviewer,
                project_id=first["project"],
                release_id=created.value.release.id,
                expected_version=2,
                idempotency_key="approve:generation:v1",
            ),
        )
        frozen = _command(
            factory,
            first["project"],
            lambda application: application.freeze_release(
                reviewer,
                project_id=first["project"],
                release_id=created.value.release.id,
                expected_version=3,
                idempotency_key="freeze:generation:v1",
            ),
        )
        created_v2 = _command(
            factory,
            first["project"],
            lambda application: application.create_release(
                owner,
                project_id=first["project"],
                program_id=created.value.program.id,
                system_template="Return concise Australian English for {{channel}}.",
                user_template="Write {{scenario}} for {{channel}} with evidence.",
                schemas=_schemas(),
                model_policy=_policy(),
                test_set_id=created.value.release.test_set_id,
                test_set_version=2,
                test_set_hash=created.value.release.test_set_hash,
                compiler_version="geo-prompt-compiler-v2",
                expected_version=1,
                idempotency_key="create-release:generation:v2",
            ),
        )
        diffed = _command(
            factory,
            first["project"],
            lambda application: application.diff_release(
                owner,
                project_id=first["project"],
                program_id=created.value.program.id,
                candidate_release_id=created_v2.value.release.id,
                baseline_release_id=created.value.release.id,
                fixed_variables={
                    "scenario": "Compare a solar retailer",
                    "channel": "Google AI Overview",
                },
                expected_version=1,
                idempotency_key="diff:generation:v1-v2",
            ),
        )
        diff_replay = _command(
            factory,
            first["project"],
            lambda application: application.diff_release(
                owner,
                project_id=first["project"],
                program_id=created.value.program.id,
                candidate_release_id=created_v2.value.release.id,
                baseline_release_id=created.value.release.id,
                fixed_variables={
                    "scenario": "Compare a solar retailer",
                    "channel": "Google AI Overview",
                },
                expected_version=1,
                idempotency_key="diff:generation:v1-v2",
            ),
        )
        assert created_v2.value.release.version == 2
        assert diffed.value.base_release_id == created.value.release.id
        assert diffed.value.candidate_release_id == created_v2.value.release.id
        assert diffed.value.changed_fields == (
            "system_template",
            "test_set",
            "user_template",
        )
        assert diff_replay.replayed is True
        assert diff_replay.value == diffed.value

        with factory(first["project"]) as unit_of_work:
            application = PromptProgramApplication(unit_of_work.prompts)
            programs = application.list_programs(
                owner, project_id=first["project"], limit=10, offset=0
            )
            releases = application.list_releases(
                owner,
                project_id=first["project"],
                program_id=created.value.program.id,
                limit=10,
                offset=0,
            )
        assert programs.total == 1
        assert [item.release.version for item in releases.items] == [2, 1]

        api = build_prompt_program_api(database_url=app_url)
        assert api.list_programs(
            owner, project_id=first["project"], limit=10, offset=0
        ).total == 1
        assert api.get_release(
            owner,
            project_id=first["project"],
            program_id=created.value.program.id,
            release_id=created_v2.value.release.id,
        ).release == created_v2.value.release
        with pytest.raises(PromptProgramNotFound, match="does not exist"):
            api.get_release(
                owner,
                project_id=first["project"],
                program_id=uuid4(),
                release_id=created_v2.value.release.id,
            )

        bound = _command(
            factory,
            first["project"],
            lambda application: application.bind_release(
                reviewer,
                project_id=first["project"],
                release_id=created.value.release.id,
                purpose="synthetic_lab.generation",
                expected_version=0,
                idempotency_key="bind:generation:v1",
            ),
        )
        resolved = _command(
            factory,
            first["project"],
            lambda application: application.resolve_runtime_binding(
                project_id=first["project"], purpose="synthetic_lab.generation"
            ),
        )
        assert resolved.release == created.value.release
        assert resolved.state == frozen.value.state
        assert resolved.binding == bound.value.binding
        assert approved.value.admitted_test_evidence == tested.value.evidence

        retired = _command(
            factory,
            first["project"],
            lambda application: application.retire_release(
                reviewer,
                project_id=first["project"],
                release_id=created.value.release.id,
                expected_version=4,
                idempotency_key="retire:generation:v1",
            ),
        )
        assert retired.value.state.status.value == "retired"
        with pytest.raises(PromptProgramRuntimeBlocked, match="exact frozen"):
            _command(
                factory,
                first["project"],
                lambda application: application.resolve_runtime_binding(
                    project_id=first["project"],
                    purpose="synthetic_lab.generation",
                ),
            )
        with factory(first["project"]) as unit_of_work:
            assert unit_of_work.prompts.list_current_bindings(
                project_id=first["project"],
                program_kind=None,
                limit=10,
                offset=0,
            ).items == ()

        with pytest.raises(PromptProgramVersionConflict, match="changed after"):
            _command(
                factory,
                first["project"],
                lambda application: application.freeze_release(
                    reviewer,
                    project_id=first["project"],
                    release_id=created.value.release.id,
                    expected_version=2,
                    idempotency_key="freeze:generation:stale",
                ),
            )

        with psycopg.connect(app_url) as connection:
            set_project_scope(connection, first["project"])
            counts = connection.execute(
                """SELECT
                     (SELECT count(*) FROM prompt_programs),
                     (SELECT count(*) FROM prompt_program_releases),
                     (SELECT count(*) FROM prompt_program_release_states),
                     (SELECT count(*) FROM prompt_program_test_evidence),
                     (SELECT count(*) FROM prompt_program_bindings),
                     (SELECT count(*) FROM prompt_program_command_receipts)"""
            ).fetchone()
            assert counts == (1, 2, 6, 1, 1, 8)

        _assert_rls_and_immutability(
            app_url=app_url,
            first=first,
            second=second,
            release_id=created.value.release.id,
        )
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=[first, second],
                tenant_ids=[first["tenant"], second["tenant"]],
                app_login=app_login,
            )


def _command(factory, project_id: UUID, operation):
    with factory(project_id) as unit_of_work:
        application = PromptProgramApplication(
            unit_of_work.prompts,
            test_evidence_verifier=_DatabaseLifecycleEvidenceVerifier(),
        )
        result = operation(application)
        unit_of_work.commit()
        return result


class _DatabaseLifecycleEvidenceVerifier:
    """Keep this test focused on PostgreSQL lifecycle and lineage constraints."""

    def verify(
        self,
        *,
        release: PromptProgramRelease,
        evidence: ProgramTestEvidence,
    ) -> None:
        assert evidence.project_id == release.project_id
        assert evidence.release_id == release.id
        assert evidence.release_hash == release.release_hash
        assert evidence.output_artifact_ref == "s3://prompt-tests/generation/fixed-run.json"
        assert evidence.output_hash == "e" * 64


def _principal(ids: dict[str, UUID], identity: str) -> AccessPrincipal:
    identity_id = ids[identity]
    return AccessPrincipal(
        identity_id=identity_id,
        actor_id=str(identity_id),
        tenant_id=ids["tenant"],
        memberships=(
            MembershipRecord(ids["project"], ids["tenant"], "admin"),
        ),
        auth_method="integration",
    )


def _schemas() -> ProgramSchemaContract:
    variables = {
        "type": "object",
        "properties": {
            "scenario": {"type": "string"},
            "channel": {"type": "string"},
        },
        "required": ["scenario", "channel"],
        "additionalProperties": False,
    }
    return ProgramSchemaContract(
        variable_schema_version="prompt-vars-v1",
        variable_schema=variables,
        input_schema_version="generation-input-v1",
        input_schema=variables,
        output_schema_version="candidate-v1",
        output_schema={
            "type": "object",
            "properties": {"candidate": {"type": "string"}},
            "required": ["candidate"],
            "additionalProperties": False,
        },
    )


def _policy() -> ModelPolicySnapshot:
    return ModelPolicySnapshot(
        version="synthetic-generation-v1",
        policy={
            "allowed_providers": ["openai", "deepseek"],
            "configured_model": "approved-generation-model",
            "fallback": False,
        },
    )


def _assert_database_rejects_owner_approval(
    *,
    app_url: str,
    project_id: UUID,
    release_id: UUID,
    release_hash: str,
    tested_state_id: UUID,
    owner_id: UUID,
) -> None:
    with psycopg.connect(app_url) as connection:
        set_project_scope(connection, project_id)
        with pytest.raises(psycopg.Error, match="owner cannot approve"):
            connection.execute(
                """INSERT INTO prompt_program_release_states
                     (id, project_id, release_id, release_hash, version,
                      previous_state_id, status, acted_by, acted_at, evidence_ref)
                   VALUES (%s, %s, %s, %s, 3, %s, 'approved', %s,
                           clock_timestamp(), 'approval:forged')""",
                (
                    uuid4(),
                    project_id,
                    release_id,
                    release_hash,
                    tested_state_id,
                    owner_id,
                ),
            )
        connection.rollback()


def _assert_database_rejects_release_version_gap(
    *, app_url: str, project_id: UUID, release_id: UUID
) -> None:
    with psycopg.connect(app_url) as connection:
        set_project_scope(connection, project_id)
        with pytest.raises(psycopg.Error, match="Release version is not linear"):
            connection.execute(
                """INSERT INTO prompt_program_releases
                     (id, project_id, program_id, program_kind, purpose, version,
                      owner_id, system_template, user_template,
                      variable_schema_version, variable_schema,
                      input_schema_version, input_schema,
                      output_schema_version, output_schema,
                      model_policy_version, model_policy, model_policy_hash,
                      test_set_id, test_set_version, compiler_version,
                      system_template_hash, user_template_hash, release_hash)
                   SELECT %s, project_id, program_id, program_kind, purpose, 3,
                          owner_id, system_template, user_template,
                          variable_schema_version, variable_schema,
                          input_schema_version, input_schema,
                          output_schema_version, output_schema,
                          model_policy_version, model_policy, model_policy_hash,
                          test_set_id, test_set_version, compiler_version,
                          system_template_hash, user_template_hash, %s
                   FROM prompt_program_releases
                   WHERE project_id = %s AND id = %s""",
                (uuid4(), "f" * 64, project_id, release_id),
            )
        connection.rollback()


def _assert_database_rejects_evidence_actor_mismatch(
    *,
    app_url: str,
    project_id: UUID,
    release: PromptProgramRelease,
    draft_state_id: UUID,
    state_actor: UUID,
    evidence_actor: UUID,
) -> None:
    state_id, evidence_id = uuid4(), uuid4()
    evidence_hash = "a" * 64
    with psycopg.connect(app_url) as connection:
        set_project_scope(connection, project_id)
        timestamp = connection.execute("SELECT clock_timestamp()").fetchone()[0]
        connection.execute(
            """INSERT INTO prompt_program_release_states
                 (id, project_id, release_id, release_hash, version,
                  previous_state_id, status, acted_by, acted_at, evidence_ref)
               VALUES (%s, %s, %s, %s, 2, %s, 'tested', %s, %s, %s)""",
            (
                state_id,
                project_id,
                release.id,
                release.release_hash,
                draft_state_id,
                state_actor,
                timestamp,
                f"prompt-test:{evidence_id}:{evidence_hash}",
            ),
        )
        connection.execute(
            """INSERT INTO prompt_program_test_evidence
                 (id, project_id, release_id, release_hash, tested_state_id,
                  test_set_id, test_set_version, output_artifact_ref, output_hash,
                  tested_by, tested_at, evidence_hash)
               VALUES (%s, %s, %s, %s, %s, %s, %s,
                       's3://prompt-tests/forged.json', %s, %s, %s, %s)""",
            (
                evidence_id,
                project_id,
                release.id,
                release.release_hash,
                state_id,
                release.test_set_id,
                release.test_set_version,
                "b" * 64,
                evidence_actor,
                timestamp,
                evidence_hash,
            ),
        )
        with pytest.raises(psycopg.Error, match="tested state evidence is inconsistent"):
            connection.commit()
        connection.rollback()


def _assert_rls_and_immutability(
    *,
    app_url: str,
    first: dict[str, UUID],
    second: dict[str, UUID],
    release_id: UUID,
) -> None:
    with psycopg.connect(app_url) as connection:
        set_project_scope(connection, second["project"])
        assert connection.execute("SELECT count(*) FROM prompt_programs").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT count(*) FROM prompt_program_releases WHERE id = %s",
                (release_id,),
            ).fetchone()[0]
            == 0
        )
        with pytest.raises(psycopg.Error, match="row-level security"):
            connection.execute(
                """INSERT INTO prompt_programs
                     (id, project_id, program_kind, purpose, owner_id)
                   VALUES (%s, %s, 'generation', 'cross.project', %s)""",
                (uuid4(), first["project"], first["owner"]),
            )
        connection.rollback()
    with psycopg.connect(ADMIN_URL) as admin:
        with pytest.raises(psycopg.Error, match="immutable"):
            admin.execute(
                "UPDATE prompt_program_releases SET purpose = 'changed' WHERE id = %s",
                (release_id,),
            )
        admin.rollback()
        with pytest.raises(psycopg.Error, match="immutable"):
            admin.execute(
                "DELETE FROM prompt_program_releases WHERE id = %s",
                (release_id,),
            )
        admin.rollback()
        assert admin.execute(
            "SELECT has_table_privilege('geo_readonly', 'prompt_program_releases', 'SELECT')"
        ).fetchone()[0] is False
