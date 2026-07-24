"""Shared fixtures and access assertions for Sampling Suite PostgreSQL tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from uuid import UUID, uuid4, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from geo_api.workflow_c_sampling_contracts import (
    AdmissionPolicyDecisionRequest,
    AdmissionPolicySubmitRequest,
    CreateAdmissionPolicyRequest,
)
from geo_core.project_scope import set_project_scope
from geo_core.sampling import (
    CaptureMethod,
    LocationControl,
    PersistentProviderSamplingExecutionInput,
    PersistentSamplingSuiteInput,
    ProviderSamplingExecutionInput,
    SamplingQuestion,
    SamplingSourceStratum,
    SamplingSuite,
)
from geo_core.sampling.postgres_suites import SAMPLING_SUITE_INPUT_NAMESPACE
from tests.integration.sampling_suite_postgres_worker_support import (
    provider_attempt_spec as _provider_attempt_spec,
)


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


def approved_policy(control, *, project_id: UUID):
    created = control.create(
        project_id=project_id,
        actor_id="maker",
        idempotency_key="sampling-suite:policy",
        payload=CreateAdmissionPolicyRequest(
            runtime_authorization_option_key="provider-au-v1",
            purpose="geo_measurement",
            valid_until=NOW + timedelta(days=7),
            quota_remaining=10,
            daily_task_limit=10,
            minimum_request_interval_seconds=1,
            max_concurrency=2,
        ),
    ).record
    submitted = control.submit(
        project_id=project_id,
        policy_id=created.id,
        actor_id="maker",
        idempotency_key="sampling-suite:policy:submit",
        payload=AdmissionPolicySubmitRequest(expected_version=created.aggregate_version),
    ).record
    return control.decide(
        project_id=project_id,
        policy_id=created.id,
        actor_id="checker",
        idempotency_key="sampling-suite:policy:approve",
        payload=AdmissionPolicyDecisionRequest(
            expected_version=submitted.aggregate_version, reason="authorized"
        ),
        approved=True,
    ).record


def suite_input(
    *,
    project_id: UUID,
    policy_id: UUID,
    policy_hash: str,
    display_name: str = "Provider AU \u6d4b\u8bd5",
) -> PersistentSamplingSuiteInput:
    option_key = "provider-au-suite-v1"
    return PersistentSamplingSuiteInput(
        id=uuid5(SAMPLING_SUITE_INPUT_NAMESPACE, f"{project_id}:{option_key}"),
        project_id=project_id,
        option_key=option_key,
        display_name=display_name,
        question_set_id=uuid4(),
        question_set_version="question-set-v1",
        question_set_hash=hash_value("question-set"),
        questions=(SamplingQuestion("q-1", "v1", hash_value("Which provider should I choose?")),),
        adapter_release_id=uuid4(),
        adapter_release_hash=hash_value("adapter-release"),
        model_release_id=uuid4(),
        model_release_hash=hash_value("model-release"),
        route_policy_id=uuid4(),
        route_policy_hash=hash_value("route-policy"),
        runtime_manifest_id=uuid4(),
        runtime_manifest_hash=hash_value("runtime-manifest"),
        runtime_option_id=uuid4(),
        runtime_option_hash=hash_value("runtime-option"),
        admission_policy_id=policy_id,
        admission_policy_hash=policy_hash,
        source_stratum=SamplingSourceStratum(
            platform="provider",
            surface="grounded_answer",
            configured_model="provider-model",
            reported_model="provider-model-v1",
            capture_method=CaptureMethod.PROVIDER_API,
            adapter_release="provider-au-release-v1",
            locale="en-AU",
            region="AU",
            language="en",
            search_mode="enabled",
            account_cohort="not_applicable",
            egress_policy_category="not_applicable",
            location_control=LocationControl.COUNTRY,
            location_evidence_hash=hash_value("location:provider-au"),
            requested_country="AU",
            requested_region=None,
            requested_locale="en-AU",
            requested_language="en",
            effective_country="AU",
            effective_region=None,
            effective_locale=None,
            effective_language=None,
        ),
        frozen_at=NOW,
    )


def suite(input_option: PersistentSamplingSuiteInput) -> SamplingSuite:
    return SamplingSuite(
        id=uuid4(),
        project_id=input_option.project_id,
        question_set_id=input_option.question_set_id,
        question_set_version=input_option.question_set_version,
        question_set_hash=input_option.question_set_hash,
        adapter_release_id=input_option.adapter_release_id,
        adapter_release_hash=input_option.adapter_release_hash,
        model_release_id=input_option.model_release_id,
        model_release_hash=input_option.model_release_hash,
        route_policy_id=input_option.route_policy_id,
        route_policy_hash=input_option.route_policy_hash,
        runtime_manifest_id=input_option.runtime_manifest_id,
        runtime_manifest_hash=input_option.runtime_manifest_hash,
        runtime_option_id=input_option.runtime_option_id,
        runtime_option_hash=input_option.runtime_option_hash,
        admission_policy_id=input_option.admission_policy_id,
        admission_policy_hash=input_option.admission_policy_hash,
        questions=input_option.questions,
        source_stratum=input_option.source_stratum,
        repetitions=10,
        statistics_method_version="sampling-statistics-v1",
        max_planned_tasks=10,
        max_daily_tasks=10,
        minimum_request_interval_seconds=1,
        max_concurrency=2,
        frozen_by="operator",
        frozen_at=NOW,
    )


def provider_execution_input(
    input_option: PersistentSamplingSuiteInput,
) -> PersistentProviderSamplingExecutionInput:
    template = _provider_attempt_spec(
        run_id=uuid4(),
        task_id=uuid4(),
        attempt_id=uuid4(),
        task_version=2,
        question_hash=input_option.questions[0].text_hash,
        admitted_at=NOW,
    )
    return PersistentProviderSamplingExecutionInput(
        project_id=input_option.project_id,
        suite_input_option_id=input_option.id,
        suite_input_option_hash=input_option.option_hash,
        execution=ProviderSamplingExecutionInput.from_payload(
            {
                "schema_version": 1,
                "runtime_selection_id": template["runtime_selection_id"],
                "prompt": template["prompt"],
                "questions": [
                    {
                        "question_id": input_option.questions[0].question_id,
                        "question_version": input_option.questions[0].question_version,
                        "text": "Which provider should I choose?",
                        "text_hash": input_option.questions[0].text_hash,
                    }
                ],
                "deadline_at": template["deadline_at"],
            }
        ),
        frozen_at=NOW,
    )


def seed_runtime_option(connection, *, project_id: UUID, marker: str) -> None:
    connection.execute(
        """INSERT INTO workflow_c_sampling_runtime_options(
               project_id, option_key, option_hash, display_name, platform,
               capture_method, adapter_release, location_control,
               location_evidence_hash, authorization_reference, allowed_purposes,
               status, frozen_at
           ) VALUES (
               %s, 'provider-au-v1', %s, 'Provider AU', 'provider', 'provider_api',
               'provider-au-release-v1', 'country', %s, %s,
               %s::jsonb, 'approved', clock_timestamp()
           )""",
        (
            project_id,
            hash_value(f"runtime-option:{marker}"),
            hash_value("location:provider-au"),
            f"authorization:{marker}",
            Jsonb(["geo_measurement"]),
        ),
    )


def assert_app_cannot_bypass_suite_commands(
    database_url: str, *, project_id: UUID, suite_id: UUID, run_id: UUID
) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        set_project_scope(connection, project_id)
        assert not boolean(
            connection,
            "SELECT has_table_privilege(current_user, 'workflow_c_sampling_suites', 'INSERT')",
        )
        assert not boolean(
            connection,
            "SELECT has_table_privilege(current_user, 'workflow_c_sampling_suite_input_options', 'INSERT')",
        )
        assert not boolean(
            connection,
            "SELECT has_table_privilege(current_user, 'workflow_c_sampling_runs', 'INSERT')",
        )
        assert not boolean(
            connection,
            "SELECT has_table_privilege(current_user, 'workflow_c_sampling_attempts', 'INSERT')",
        )
        assert not boolean(
            connection,
            """SELECT has_function_privilege(
                   current_user,
                   to_regprocedure(
                       'geo_enqueue_workflow_c_provider_sampling_attempt('
                       'uuid,uuid,text,text,uuid,uuid,integer,text,jsonb,text,timestamptz)'
                   ),
                   'EXECUTE'
               )""",
        )
        assert boolean(
            connection,
            """SELECT has_function_privilege(
                   current_user,
                   to_regprocedure(
                       'geo_schedule_workflow_c_provider_sampling_attempt('
                       'uuid,uuid,text,text,uuid,uuid,integer,text,jsonb,text,timestamptz,timestamptz)'
                   ),
                   'EXECUTE'
               )""",
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """UPDATE workflow_c_sampling_suites SET suite_hash = %s
                   WHERE project_id = %s AND id = %s""",
                (hash_value("wrong"), project_id, suite_id),
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """UPDATE workflow_c_sampling_runs SET reserved_task_count = 0
                   WHERE project_id = %s AND id = %s""",
                (project_id, run_id),
            )
        connection.rollback()


def assert_scope_rejects_foreign_project(
    database_url: str,
    *,
    scoped_project_id: UUID,
    foreign_project_id: UUID,
    frozen_suite: SamplingSuite,
    input_option: PersistentSamplingSuiteInput,
) -> None:
    with psycopg.connect(database_url) as connection:
        set_project_scope(connection, scoped_project_id)
        payload = {
            "schema_version": 1,
            "suite": frozen_suite.canonical_value(),
            "frozen_by": frozen_suite.frozen_by,
            "frozen_at": frozen_suite.frozen_at.isoformat(),
        }
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """SELECT * FROM geo_create_workflow_c_sampling_suite(
                       %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s
                   )""",
                (
                    foreign_project_id,
                    frozen_suite.id,
                    hash_value("foreign-key"),
                    hash_value("foreign-command"),
                    input_option.id,
                    input_option.option_hash,
                    frozen_suite.suite_hash,
                    Jsonb(payload),
                    NOW,
                ),
            )
        connection.rollback()


def assert_canonical_payload_hash(
    database_url: str, project_id: UUID, input_option: PersistentSamplingSuiteInput
) -> None:
    payload = input_option.payload()
    with psycopg.connect(database_url) as connection:
        set_project_scope(connection, project_id)
        canonical, digest = connection.execute(
            """SELECT geo_jsonb_sampling_canonical_text(%s::jsonb),
                      encode(
                          digest(
                              convert_to(geo_jsonb_sampling_canonical_text(%s::jsonb), 'UTF8'),
                              'sha256'
                          ),
                          'hex'
                      )""",
            (Jsonb(payload), Jsonb(payload)),
        ).fetchone()
    assert canonical == json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert digest == input_option.option_hash


def boolean(connection, statement: str) -> bool:
    row = connection.execute(statement).fetchone()
    if isinstance(row, dict):
        return bool(next(iter(row.values())))
    return bool(row[0])


def hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
