from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4, uuid5

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from geo_api.workflow_c_sampling_contracts import (
    AdmissionPolicyDecisionRequest,
    AdmissionPolicySubmitRequest,
    CreateAdmissionPolicyRequest,
)
from geo_api.workflow_c_sampling_postgres_policy import PostgresWorkflowCSamplingPolicyControl
from geo_core.browser_capture.admin import BrowserCaptureAdminService
from geo_core.browser_capture.admission import BrowserCaptureAttemptAdmissionService
from geo_core.browser_capture.bulk_admission import BrowserCaptureBulkAdmissionService
from geo_core.browser_capture.artifacts import BrowserArtifactBundle
from geo_core.browser_capture.domain import (
    BrowserCaptureError,
    EgressObservation,
    NetworkType,
    evaluate_egress,
)
from geo_core.browser_capture.egress_test import (
    BrowserEgressTestOperation,
    PostgresBrowserEgressTestRepository,
)
from geo_core.browser_capture.parsing import Citation, PageSignals, SurfaceRelease, parse_capture
from geo_core.browser_capture.playwright_driver import PlaywrightCapture, ProxyLease
from geo_core.browser_capture.worker import PostgresBrowserCaptureWorkerRepository
from geo_core.alerts import AlertRuleKind, AlertSeverity
from geo_core.alerts.postgres_operations import PostgresWorkflowCAlertEvaluateOperation
from geo_core.connectors.contracts import canonical_hash
from geo_core.connectors.external_data import ExternalDataService
from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.project_scope import set_project_scope
from geo_core.workflow_c_alert_admission import (
    AlertEvaluationSelector,
    PostgresWorkflowCAlertAdmissionRepository,
)
from geo_core.workflow_c_alert_rules import (
    AlertRuleReleaseStatus,
    PostgresWorkflowCAlertRuleRepository,
)
from geo_core.workflow_c_job_specs import PostgresWorkflowCJobSpecRepository
from geo_core.sampling import (
    CaptureMethod,
    LocationControl,
    PersistentSamplingSuiteInput,
    PostgresSamplingRunRepository,
    PostgresSamplingSuiteRepository,
    SamplingAdmissionCommand,
    SamplingQuestion,
    SamplingSourceStratum,
    SamplingSuite,
    admit_sampling_suite,
)
from geo_core.sampling.postgres_admission import PostgresSamplingAdmissionRepository
from geo_core.sampling.postgres_suites import SAMPLING_SUITE_INPUT_NAMESPACE
from tests.integration.placement_worker_support import seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


class _ProxyCredentials:
    def resolve(self, **_: object) -> dict[str, object]:
        return {"provider": "lokiproxy", "pool_product": "rotating_residential", "username": "loki-account", "password": "test-secret", "username_template": "{username}-session-{session_id}", "lease_ttl_seconds": 600}


class _EgressDriver:
    def verify_egress(self, *, proxy: ProxyLease, probes: object, now: datetime):
        del probes
        observations = tuple(
            EgressObservation(source, "1.1.1.1", "AU", "NSW", "AS13335", now)
            for source in ("geo-a", "geo-b")
        )
        return evaluate_egress(
            verification_id=uuid4(), sticky_lease_hash=proxy.lease_hash,
            pre=observations, post=observations, network_type=proxy.network_type,
            expected_region=proxy.expected_region,
        )


def test_browser_attempt_commits_one_fenced_sampling_observation() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_browser_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    created = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        command.upgrade(migration, "head")
        now = datetime.now(UTC).replace(microsecond=0)
        with psycopg.connect(database_url, row_factory=dict_row) as admin:
            seeded = seed_project(admin, suffix=f"browser-{suffix}")
            campaign_id = uuid4()
            admin.execute(
                """INSERT INTO geo_campaigns(
                       id, project_id, market_profile_id, primary_product_entity_id,
                       name, created_by
                   ) VALUES (%s, %s, %s, %s, 'Browser capture fixture', %s)""",
                (
                    campaign_id,
                    seeded["project"],
                    seeded["market"],
                    seeded["entity"],
                    seeded["owner"],
                ),
            )
            secret_id = _active_proxy_secret(admin, seeded=seeded, now=now)
            question_set_id, question_id, question_hash = _frozen_question(
                admin, seeded=seeded, campaign_id=campaign_id, now=now
            )

        def connect():
            return psycopg.connect(database_url, row_factory=dict_row)

        browser = BrowserCaptureAdminService(connect=connect, clock=lambda: now)
        release = browser.create_surface_release(
            project_id=seeded["project"],
            actor_id=seeded["owner"],
            platform="google",
            surface="google_ai_overviews",
            release_version="integration-v1",
            entry_url_template="https://www.google.com/",
            allowed_hosts=("www.google.com",),
            selectors={
                "query_input": "textarea[name='q']",
                "page_complete": "#search",
                "surface_marker": "[data-aio]",
                "answer": "[data-answer]",
                "citations": "[data-citation]",
                "page_location": "[data-location]",
            },
            block_detectors={"captcha": "form[action*='sorry']"},
            parser_release="google-aio-parser-v1",
            browser_release="playwright:1.60.0/chromium",
            authorization_track="A",
            authorization_status="approved",
            authorization_reference="integration-authorization",
            authorization_valid_until=now + timedelta(days=7),
            terms_version="integration-v1",
        )
        release = browser.approve_surface_release(
            project_id=seeded["project"],
            release_id=release["id"],
            reviewer_id=seeded["reviewer"],
        )
        endpoint = browser.install_egress_endpoint(
            project_id=seeded["project"],
            actor_id=seeded["owner"],
            name="AU integration proxy",
            protocol="https",
            endpoint_host="proxy.example.test",
            endpoint_port=443,
            secret_reference_id=secret_id,
            secret_purpose="browser_egress.lokiproxy",
            secret_version=1,
            expected_region="NSW",
            network_type="residential",
            provider="lokiproxy",
            egress_policy_version="integration-v1",
            egress_cohort_key="au-residential-integration",
            pool_product="rotating_residential", session_ttl_seconds=600,
        )
        egress_test = browser.test_egress_endpoint(
            project_id=seeded["project"], actor_id=seeded["owner"],
            endpoint_id=endpoint["id"], idempotency_key="egress-test-1",
        )
        replay = browser.test_egress_endpoint(
            project_id=seeded["project"], actor_id=seeded["owner"],
            endpoint_id=endpoint["id"], idempotency_key="egress-test-1",
        )
        assert replay["test_id"] == egress_test["test_id"]
        assert replay["replayed"] is True
        store = PostgresDurableJobStore(connect)
        claim = store.claim(
            job_id=egress_test["job_id"], project_id=seeded["project"],
            expected_kind="browser.egress_test", worker_id="egress-test-worker",
            lease_for=timedelta(minutes=5),
        )
        assert claim.lease is not None
        operation = BrowserEgressTestOperation(
            store=store,
            repository=PostgresBrowserEgressTestRepository(connect=connect),
            credentials=_ProxyCredentials(),
            probes=(object(), object()),
            driver=_EgressDriver(),
            lease_for=timedelta(minutes=5),
            clock=lambda: now,
        )
        assert operation.execute(claim.lease)["eligible"] is True
        tested = browser.inventory(project_id=seeded["project"])["egress_tests"][0]
        assert tested["status"] == "succeeded"
        assert tested["outcome"] == "au_consumer_representative"
        assert tested["eligible"] is True
        assert tested["verification_hash"]
        assert browser.inventory(project_id=seeded["project"])["egress_endpoints"][0]["health_status"] == "healthy"
        profile = browser.create_profile(
            project_id=seeded["project"],
            actor_id=seeded["owner"],
            version="integration-au-desktop",
            browser_release="playwright:1.60.0/chromium",
            device_class="desktop",
            viewport={"width": 1440, "height": 1000},
            timezone="Australia/Sydney",
            geolocation={"latitude": -33.8688, "longitude": 151.2093, "accuracy": 25},
            location_permission=True,
            safe_search="moderate",
            account_cohort="clean_anonymous",
        )
        profile = browser.approve_profile(
            project_id=seeded["project"],
            profile_id=profile["id"],
            reviewer_id=seeded["reviewer"],
        )
        option = browser.register_sampling_runtime_option(
            project_id=seeded["project"],
            surface_release_id=release["id"],
            egress_endpoint_id=endpoint["id"],
            profile_version_id=profile["id"],
        )
        policies = PostgresWorkflowCSamplingPolicyControl(
            repository=PostgresSamplingAdmissionRepository(connect=connect, clock=lambda: now),
            clock=lambda: now,
        )
        draft = policies.create(
            project_id=seeded["project"],
            actor_id="maker",
            idempotency_key="browser-policy",
            payload=CreateAdmissionPolicyRequest(
                runtime_authorization_option_key=str(option["option_key"]),
                purpose="geo_measurement",
                valid_until=now + timedelta(days=7),
                    quota_remaining=4,
                    daily_task_limit=4,
                minimum_request_interval_seconds=0,
                max_concurrency=1,
            ),
        ).record
        submitted = policies.submit(
            project_id=seeded["project"],
            policy_id=draft.id,
            actor_id="maker",
            idempotency_key="browser-policy-submit",
            payload=AdmissionPolicySubmitRequest(expected_version=draft.aggregate_version),
        ).record
        policy = policies.decide(
            project_id=seeded["project"],
            policy_id=draft.id,
            actor_id="checker",
            idempotency_key="browser-policy-approve",
            payload=AdmissionPolicyDecisionRequest(
                expected_version=submitted.aggregate_version,
                reason="approved integration authorization",
            ),
            approved=True,
        ).record
        source = SamplingSourceStratum(
            platform="google",
            surface="google_ai_overviews",
            configured_model="not_applicable",
            reported_model="not_applicable",
            capture_method=CaptureMethod.AUTOMATED_UI,
            adapter_release=str(option["adapter_release"]),
            locale="en-AU",
            region="AU",
            language="en",
            search_mode="enabled",
            account_cohort="clean_anonymous",
            egress_policy_category="residential:integration-v1:au-residential-integration",
            location_control=LocationControl.COUNTRY,
            location_evidence_hash=str(option["location_evidence_hash"]),
            requested_country="AU",
            requested_region=None,
            requested_locale="en-AU",
            requested_language="en",
            effective_country="AU",
            effective_region=None,
            effective_locale=None,
            effective_language=None,
        )
        route_hash = canonical_hash(
            {
                key: endpoint[key]
                for key in (
                    "id",
                    "network_type",
                    "sticky_mode",
                    "egress_policy_version",
                    "egress_cohort_key",
                    "expected_country",
                    "expected_region",
                )
            }
        )
        input_option = PersistentSamplingSuiteInput(
            id=uuid5(
                SAMPLING_SUITE_INPUT_NAMESPACE,
                f"{seeded['project']}:browser-integration",
            ),
            project_id=seeded["project"],
            option_key="browser-integration",
            display_name="Browser integration",
            question_set_id=question_set_id,
            question_set_version="v1",
            question_set_hash=canonical_hash({"question_set": str(question_set_id)}),
            questions=(SamplingQuestion(str(question_id), "v1", question_hash),),
            adapter_release_id=release["id"],
            adapter_release_hash=release["release_hash"],
            model_release_id=profile["id"],
            model_release_hash=profile["profile_hash"],
            route_policy_id=endpoint["id"],
            route_policy_hash=route_hash,
            runtime_manifest_id=release["id"],
            runtime_manifest_hash=release["release_hash"],
            runtime_option_id=profile["id"],
            runtime_option_hash=profile["profile_hash"],
            admission_policy_id=policy.id,
            admission_policy_hash=policy.definition_hash,
            source_stratum=source,
            frozen_at=now,
        )
        suites = PostgresSamplingSuiteRepository(connect=connect)
        suites.register_input(input_option, idempotency_key="browser-input")
        suite = SamplingSuite(
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
            source_stratum=source,
            repetitions=4,
            statistics_method_version="sampling-statistics-v1",
            max_planned_tasks=4,
            max_daily_tasks=4,
            minimum_request_interval_seconds=0,
            max_concurrency=1,
            frozen_by="integration",
            frozen_at=now,
        )
        suites.create_suite(suite, input_option=input_option, idempotency_key="browser-suite")
        grant = admit_sampling_suite(
            suite,
            policy=policy.approved_policy(at=now),
            command=SamplingAdmissionCommand(
                idempotency_key="browser-run",
                purpose="geo_measurement",
                requested_at=now,
                requested_not_before=now,
            ),
        )
        runs = PostgresSamplingRunRepository(connect=connect)
        run, tasks = runs.create_run(
            suite=suite,
            grant=grant,
            run_id=uuid4(),
            idempotency_key="browser-run",
            created_at=now,
        )
        inventory_before = browser.inventory(project_id=seeded["project"])
        listed_before = next(
            item for item in inventory_before["tasks"] if item["id"] == tasks[0].id
        )
        assert listed_before["status"] == "planned"
        assert listed_before["attempt_id"] is None
        assert listed_before["surface_release_id"] == str(release["id"])
        assert listed_before["egress_endpoint_id"] == str(endpoint["id"])
        assert listed_before["profile_version_id"] == str(profile["id"])
        assert run.admitted_not_before <= now < run.authorization_valid_until
        assert policy.status.value == "approved"
        assert policy.effective_authorization_state(at=now).value == "approved"
        assert now < policy.valid_until
        assert release["status"] == "approved"
        assert release["authorization_status"] == "approved"
        assert now < release["authorization_valid_until"]
        assert endpoint["status"] == "approved"
        assert endpoint["expected_country"] == "AU"
        assert endpoint["network_type"] == "residential"
        assert profile["status"] == "approved"
        assert suite.adapter_release_id == release["id"]
        assert suite.route_policy_id == endpoint["id"]
        assert suite.model_release_id == profile["id"]
        with connect() as connection:
            set_project_scope(connection, seeded["project"])
            persisted = connection.execute(
                """SELECT task.run_id = run.id AS task_run_matches,
                          task.suite_id = suite.id AS task_suite_matches,
                          task.status AS task_status,
                          task.version AS task_version,
                          task.capture_method AS task_capture_method,
                          suite.capture_method AS suite_capture_method,
                          run.status AS run_status,
                          policy.status AS policy_status,
                          policy.effective_authorization_state,
                          secret.status AS secret_status
                     FROM workflow_c_sampling_tasks task
                     JOIN workflow_c_sampling_runs run
                       ON run.project_id = task.project_id AND run.id = task.run_id
                     JOIN workflow_c_sampling_suites suite
                       ON suite.project_id = task.project_id AND suite.id = task.suite_id
                     JOIN workflow_c_sampling_admission_policies policy
                       ON policy.project_id = run.project_id
                      AND policy.id = run.admission_policy_id
                     JOIN browser_egress_endpoints endpoint
                       ON endpoint.project_id = task.project_id AND endpoint.id = %s
                     LEFT JOIN secret_versions secret
                       ON secret.reference_id = endpoint.secret_reference_id
                      AND secret.project_id = endpoint.project_id
                      AND secret.purpose = endpoint.secret_purpose
                      AND secret.version = endpoint.secret_version
                    WHERE task.project_id = %s AND task.id = %s""",
                (endpoint["id"], seeded["project"], tasks[0].id),
            ).fetchone()
        assert persisted == {
            "task_run_matches": True,
            "task_suite_matches": True,
            "task_status": "planned",
            "task_version": tasks[0].version,
            "task_capture_method": "automated_ui",
            "suite_capture_method": "automated_ui",
            "run_status": "planned",
            "policy_status": "approved",
            "effective_authorization_state": "approved",
            "secret_status": "active",
        }

        admission = BrowserCaptureAttemptAdmissionService(connect=connect, clock=lambda: now)
        admitted = admission.enqueue(
            project_id=seeded["project"],
            run_id=run.id,
            task_id=tasks[0].id,
            expected_task_version=tasks[0].version,
            surface_release_id=release["id"],
            egress_endpoint_id=endpoint["id"],
            profile_version_id=profile["id"],
            requested_not_before=now,
            idempotency_key="browser-attempt-1",
        )
        inventory_after = browser.inventory(project_id=seeded["project"])
        listed_after = next(
            item for item in inventory_after["tasks"] if item["id"] == tasks[0].id
        )
        assert listed_after["status"] == "queued"
        assert listed_after["attempt_id"] == admitted["attempt_id"]
        assert listed_after["durable_job_id"] == admitted["durable_job_id"]
        store = PostgresDurableJobStore(connect)
        claim = store.claim(
            job_id=admitted["durable_job_id"],
            project_id=seeded["project"],
            expected_kind="browser.capture",
            worker_id="browser-integration",
            lease_for=timedelta(minutes=5),
        )
        assert claim.lease is not None
        repository = PostgresBrowserCaptureWorkerRepository(connect=connect)
        preparation = repository.prepare(claim.lease)
        proxy = ProxyLease(
            server="https://proxy.example.test:443",
            username="integration",
            password="not-persisted",
            lease_id="provider-lease-integration",
            started_at=now,
            expires_at=now + timedelta(minutes=10),
            network_type=NetworkType.RESIDENTIAL,
            expected_region="NSW",
        )
        execution = repository.start(claim.lease, preparation=preparation, proxy=proxy)
        observations = tuple(
            EgressObservation(
                source=source_name,
                observed_ip="1.1.1.1",
                country="AU",
                region="NSW",
                asn="AS13335",
                observed_at=now,
            )
            for source_name in ("probe-a", "probe-b")
        )
        verification = evaluate_egress(
            verification_id=uuid4(),
            sticky_lease_hash=proxy.lease_hash,
            pre=observations,
            post=observations,
            network_type=NetworkType.RESIDENTIAL,
            expected_region="NSW",
        )
        capture = PlaywrightCapture(
            verification=verification,
            signals=PageSignals(
                final_url="https://www.google.com/search?q=coffee",
                page_complete=True,
                detected_surface="google_ai_overviews",
                answer_text="Australian coffee answer",
                answer_locator="[data-answer]",
                citations=(
                    Citation("Example", "https://example.test/source", 1, "[data-citation]"),
                ),
                page_country="AU",
            ),
            screenshot=b"png",
            dom=b"html",
            har=b"har",
        )
        parsed = parse_capture(
            release=SurfaceRelease(
                id=release["id"],
                platform="google",
                surface="google_ai_overviews",
                release_hash=release["release_hash"],
                parser_release=release["parser_release"],
                allowed_hosts=("www.google.com",),
            ),
            egress=verification,
            signals=capture.signals,
        )
        bundle = BrowserArtifactBundle(
            manifest_uri=f"s3://browser-test/{execution.capture_session_id}/manifest.json",
            manifest_hash="a" * 64,
            screenshot_hash="b" * 64,
            dom_hash="c" * 64,
            har_hash="d" * 64,
            encryption_key_reference="browser-artifact:v1",
            retention_until=now + timedelta(days=30),
        )
        with store.fenced_transaction(claim.lease) as connection:
            observation_id = repository.commit(
                connection,
                lease=claim.lease,
                execution=execution,
                capture=capture,
                parsed=parsed,
                bundle=bundle,
                observed_at=now,
            )
            store.complete_in_transaction(
                connection,
                claim.lease,
                result_ref=f"workflow-c-observation:{observation_id}",
                details={"observation_id": str(observation_id)},
            )
        retry_admitted = admission.enqueue(
            project_id=seeded["project"],
            run_id=run.id,
            task_id=tasks[1].id,
            expected_task_version=tasks[1].version,
            surface_release_id=release["id"],
            egress_endpoint_id=endpoint["id"],
            profile_version_id=profile["id"],
            requested_not_before=now,
            idempotency_key="browser-attempt-retry",
        )
        first_retry_claim = store.claim(
            job_id=retry_admitted["durable_job_id"],
            project_id=seeded["project"],
            expected_kind="browser.capture",
            worker_id="browser-integration",
            lease_for=timedelta(minutes=5),
        )
        assert first_retry_claim.lease is not None
        retry_preparation = repository.prepare(first_retry_claim.lease)
        first_retry_execution = repository.start(
            first_retry_claim.lease,
            preparation=retry_preparation,
            proxy=proxy,
        )
        assert store.fail(
            first_retry_claim.lease,
            error_code="browser_capture_failed",
            details={"classification": "TimeoutError"},
            retry_delay=timedelta(0),
        ) == "retry_wait"
        second_retry_claim = store.claim(
            job_id=retry_admitted["durable_job_id"],
            project_id=seeded["project"],
            expected_kind="browser.capture",
            worker_id="browser-integration",
            lease_for=timedelta(minutes=5),
        )
        assert second_retry_claim.lease is not None
        second_retry_execution = repository.start(
            second_retry_claim.lease,
            preparation=repository.prepare(second_retry_claim.lease),
            proxy=proxy,
        )
        assert first_retry_execution.execution_ordinal == 1
        assert second_retry_execution.execution_ordinal == 2
        assert store.fail(
            second_retry_claim.lease,
            error_code="browser_capture_contract_invalid",
            details={"classification": "BrowserCaptureError"},
            retry_delay=None,
        ) == "failed"
        with connect() as connection:
            set_project_scope(connection, seeded["project"])
            result = connection.execute(
                """SELECT durable.status AS job_status, attempt.status AS attempt_status,
                          task.status AS task_status, observation.status AS evidence_status,
                          parsed.result_class, verification.outcome
                     FROM durable_jobs durable
                     JOIN workflow_c_sampling_attempts attempt
                       ON attempt.project_id = durable.project_id
                      AND attempt.durable_job_id = durable.id
                     JOIN workflow_c_sampling_tasks task
                       ON task.project_id = attempt.project_id AND task.id = attempt.task_id
                     JOIN workflow_c_sampling_observations observation
                       ON observation.project_id = attempt.project_id
                      AND observation.attempt_id = attempt.id
                     JOIN browser_parsed_observations parsed
                       ON parsed.project_id = attempt.project_id
                      AND parsed.sampling_attempt_id = attempt.id
                     JOIN browser_egress_verifications verification
                       ON verification.project_id = attempt.project_id
                      AND verification.sampling_attempt_id = attempt.id
                    WHERE durable.project_id = %s AND durable.id = %s""",
                (seeded["project"], admitted["durable_job_id"]),
            ).fetchone()
            retry_result = connection.execute(
                """SELECT durable.status AS job_status, attempt.status AS attempt_status,
                          task.status AS task_status,
                          array_agg(session.status ORDER BY session.execution_ordinal) AS sessions
                     FROM durable_jobs durable
                     JOIN workflow_c_sampling_attempts attempt
                       ON attempt.project_id = durable.project_id
                      AND attempt.durable_job_id = durable.id
                     JOIN workflow_c_sampling_tasks task
                       ON task.project_id = attempt.project_id AND task.id = attempt.task_id
                     JOIN browser_capture_sessions session
                       ON session.project_id = attempt.project_id
                      AND session.sampling_attempt_id = attempt.id
                    WHERE durable.project_id = %s AND durable.id = %s
                    GROUP BY durable.status, attempt.status, task.status""",
                (seeded["project"], retry_admitted["durable_job_id"]),
            ).fetchone()
        assert result == {
            "job_status": "succeeded",
            "attempt_status": "succeeded",
            "task_status": "succeeded",
            "evidence_status": "complete",
            "result_class": "captured",
            "outcome": "au_consumer_representative",
        }
        assert retry_result == {
            "job_status": "failed",
            "attempt_status": "failed",
            "task_status": "failed",
            "sessions": ["orphaned", "orphaned"],
        }
        disabled_endpoint = browser.set_egress_endpoint_status(project_id=seeded["project"], endpoint_id=endpoint["id"], status="disabled")
        assert disabled_endpoint["status"] == "disabled" and disabled_endpoint["disabled_at"] == now
        with pytest.raises(BrowserCaptureError, match="not active"):
            browser.test_egress_endpoint(project_id=seeded["project"], actor_id=seeded["owner"], endpoint_id=endpoint["id"], idempotency_key="disabled-egress-test")
        with pytest.raises(BrowserCaptureError, match="stale"):
            admission.enqueue(
                project_id=seeded["project"], run_id=run.id, task_id=tasks[2].id,
                expected_task_version=tasks[2].version, surface_release_id=release["id"],
                egress_endpoint_id=endpoint["id"], profile_version_id=profile["id"],
                requested_not_before=now, idempotency_key="browser-disabled-egress",
            )
        enabled_endpoint = browser.set_egress_endpoint_status(project_id=seeded["project"], endpoint_id=endpoint["id"], status="approved")
        assert enabled_endpoint["status"] == "approved" and enabled_endpoint["disabled_at"] is None
        recheck = browser.test_egress_endpoint(project_id=seeded["project"], actor_id=seeded["owner"], endpoint_id=endpoint["id"], idempotency_key="enabled-egress-recheck")
        recheck_claim = store.claim(
            job_id=recheck["job_id"], project_id=seeded["project"], expected_kind="browser.egress_test",
            worker_id="egress-test-worker", lease_for=timedelta(minutes=5),
        )
        assert recheck_claim.lease is not None
        assert operation.execute(recheck_claim.lease)["eligible"] is True
        drift_admitted = admission.enqueue(
            project_id=seeded["project"], run_id=run.id, task_id=tasks[2].id,
            expected_task_version=tasks[2].version,
            surface_release_id=release["id"], egress_endpoint_id=endpoint["id"],
            profile_version_id=profile["id"], requested_not_before=now,
            idempotency_key="browser-runtime-drift",
        )
        bulk_admission = BrowserCaptureBulkAdmissionService(connect=connect)
        bulk = bulk_admission.enqueue_ready(
            project_id=seeded["project"], run_id=run.id,
            surface_release_id=release["id"], egress_endpoint_id=endpoint["id"],
            profile_version_id=profile["id"],
            task_versions=((tasks[3].id, tasks[3].version),),
            requested_not_before=now, authorization_checked_at=now, max_tasks=1,
            idempotency_key="browser-bulk-attempts",
        )
        assert bulk.enqueued_count == 1
        assert bulk.skipped_count == 3
        assert bulk.replayed is False
        replayed_bulk = bulk_admission.enqueue_ready(
            project_id=seeded["project"], run_id=run.id,
            surface_release_id=release["id"], egress_endpoint_id=endpoint["id"],
            profile_version_id=profile["id"],
            task_versions=((tasks[3].id, tasks[3].version),),
            requested_not_before=now, authorization_checked_at=now, max_tasks=1,
            idempotency_key="browser-bulk-attempts",
        )
        assert replayed_bulk.replayed is True
        assert replayed_bulk.attempts == bulk.attempts
        drift_claim = store.claim(
            job_id=drift_admitted["durable_job_id"], project_id=seeded["project"],
            expected_kind="browser.capture", worker_id="browser-integration",
            lease_for=timedelta(minutes=5),
        )
        assert drift_claim.lease is not None
        drift_preparation = repository.prepare(drift_claim.lease)
        with pytest.raises(BrowserCaptureError, match="Browser runtime drift"):
            repository.assert_browser_runtime(
                drift_claim.lease, preparation=drift_preparation,
                observed_release="playwright:1.61.0/chromium", detected_at=now,
            )
        drift_inventory = browser.inventory(project_id=seeded["project"])
        drifted_release = next(
            item for item in drift_inventory["surface_releases"]
            if item["id"] == release["id"]
        )
        assert drifted_release["status"] == "suspended"
        assert drifted_release["suspension_reason"] == "browser_build_drift"
        assert drift_inventory["drift_events"][0]["release_suspended"] is True
        alert_input = ExternalDataService(connect=connect).list_operational_alert_inputs(
            project_id=seeded["project"]
        )[0]
        assert alert_input["signal_kind"] == "browser_build"
        assert alert_input["severity"] == "critical"
        assert alert_input["payload"]["release_suspended"] is True
        alert_rules = PostgresWorkflowCAlertRuleRepository(connect=connect, clock=lambda: now)
        alert_draft = alert_rules.create(
            project_id=seeded["project"], rule_key="external-browser-health", version=1,
            kind=AlertRuleKind.EXTERNAL_HEALTH, severity=AlertSeverity.CRITICAL,
            parameters={
                "schema_version": "alert-rule-external-health-v1",
                "minimum_severity": "warning",
            },
            actor_id="external-alert-maker", idempotency_key="external-alert-rule",
        )
        alert_rule = alert_rules.transition(
            project_id=seeded["project"], rule_id=alert_draft.id,
            expected_aggregate_version=alert_draft.aggregate_version,
            target_status=AlertRuleReleaseStatus.APPROVED,
            actor_id="external-alert-checker", reason="external health rule reviewed",
            idempotency_key="external-alert-rule-approve",
        )
        alert_job = PostgresWorkflowCAlertAdmissionRepository(
            connect=connect, clock=lambda: now
        ).enqueue(
            project_id=seeded["project"],
            selector=AlertEvaluationSelector(
                alert_rule_id=alert_rule.id, source_hash=alert_input["input_hash"]
            ),
            actor_id="external-alert-operator",
            idempotency_key="external-browser-alert-evaluation",
        )
        alert_claim = store.claim(
            job_id=alert_job.job_id, project_id=seeded["project"],
            expected_kind="workflow_c.alert.evaluate", worker_id="alert-integration",
            lease_for=timedelta(minutes=5),
        )
        assert alert_claim.lease is not None
        alert_result = PostgresWorkflowCAlertEvaluateOperation(
            store=store, specs=PostgresWorkflowCJobSpecRepository(connect), clock=lambda: now
        ).execute(alert_claim.lease)
        assert alert_result["status"] == "matched"
        assert alert_result["notification_count"] == 3
        assert store.fail(
            drift_claim.lease, error_code="browser_runtime_drift",
            details={"classification": "BrowserCaptureError"}, retry_delay=None,
        ) == "failed"
        retired_release = browser.retire_surface_release(
            project_id=seeded["project"], release_id=release["id"]
        )
        assert retired_release["status"] == "retired"
        with pytest.raises(BrowserCaptureError, match="stale"):
            admission.enqueue(
                project_id=seeded["project"], run_id=run.id, task_id=tasks[2].id,
                expected_task_version=tasks[2].version,
                surface_release_id=release["id"], egress_endpoint_id=endpoint["id"],
                profile_version_id=profile["id"], requested_not_before=now,
                idempotency_key="browser-retired-surface",
            )
        with connect() as connection:
            set_project_scope(connection, seeded["project"])
            assert connection.execute(
                """SELECT count(*) FROM durable_jobs
                    WHERE project_id = %s
                      AND kind = 'browser.capture'""",
                (seeded["project"],),
            ).fetchone()["count"] == 4
            assert connection.execute(
                """SELECT count(*) FROM durable_jobs
                    WHERE project_id = %s AND kind = 'browser.egress_test'""",
                (seeded["project"],),
            ).fetchone()["count"] == 2
    finally:
        if created:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )


def _active_proxy_secret(connection, *, seeded: dict[str, UUID], now: datetime) -> UUID:
    reference_id = uuid4()
    connection.execute(
        """INSERT INTO secret_master_key_versions(
               master_key_version, algorithm, status, canary_nonce, canary_ciphertext,
               created_at, activated_at
           ) VALUES (1, 'AES-256-GCM', 'encrypt_decrypt', %s, %s, %s, %s)""",
        (b"n" * 12, b"c" * 17, now, now),
    )
    connection.execute(
        """INSERT INTO secret_references(
               id, project_id, purpose, aggregate_version, current_version,
               created_by, created_at, updated_at
           ) VALUES (%s, %s, 'browser_egress.lokiproxy', 1, NULL, %s, %s, %s)""",
        (reference_id, seeded["project"], seeded["owner"], now, now),
    )
    connection.execute(
        """INSERT INTO secret_versions(
               reference_id, project_id, purpose, version, ciphertext, data_nonce,
               wrapped_data_key, wrap_nonce, master_key_version, algorithm,
               created_at, status, created_by
           ) VALUES (%s, %s, 'browser_egress.lokiproxy', 1, %s, %s, %s, %s, 1,
                     'AES-256-GCM', %s, 'pending', %s)""",
        (
            reference_id,
            seeded["project"],
            b"x" * 17,
            b"d" * 12,
            b"w" * 48,
            b"q" * 12,
            now,
            seeded["owner"],
        ),
    )
    connection.execute(
        """UPDATE secret_versions SET verified_by = %s, verified_at = %s
             WHERE reference_id = %s AND project_id = %s AND version = 1""",
        (seeded["reviewer"], now, reference_id, seeded["project"]),
    )
    connection.execute(
        """UPDATE secret_versions
              SET status = 'active', activated_by = %s, activated_at = %s
            WHERE reference_id = %s AND project_id = %s AND version = 1""",
        (seeded["reviewer"], now, reference_id, seeded["project"]),
    )
    connection.execute(
        """UPDATE secret_references
              SET current_version = 1, aggregate_version = 2, updated_at = %s
            WHERE id = %s AND project_id = %s""",
        (now, reference_id, seeded["project"]),
    )
    return reference_id


def _frozen_question(
    connection,
    *,
    seeded: dict[str, UUID],
    campaign_id: UUID,
    now: datetime,
) -> tuple[UUID, UUID, str]:
    question_set_id, question_id, generated_job = uuid4(), uuid4(), uuid4()
    text = "What coffee product would an Australian consumer choose?"
    text_hash = canonical_hash({"text": text})
    connection.execute("SET LOCAL session_replication_role = replica")
    connection.execute(
        """INSERT INTO knowledge_question_sets(
               id, project_id, campaign_id, series_id, version_number, generated_by_job_id,
               name, status, dimension_count, covered_dimension_count,
               possible_duplicate_count, coverage_ratio, duplicate_ratio, content_hash,
               created_by, approved_by, approved_at, frozen_by, frozen_at
           ) VALUES (%s, %s, %s, %s, 1, %s, 'Browser integration questions', 'frozen',
                     1, 1, 0, 1, 0, %s, %s, %s, %s, %s, %s)""",
        (
            question_set_id,
            seeded["project"],
            campaign_id,
            question_set_id,
            generated_job,
            canonical_hash({"question_set": str(question_set_id)}),
            seeded["owner"],
            seeded["reviewer"],
            now,
            seeded["reviewer"],
            now,
        ),
    )
    connection.execute(
        """INSERT INTO knowledge_question_set_items(
               id, project_id, campaign_id, question_set_id, generated_by_job_id,
               question_candidate_id, ordinal, dimension_key, query_text_snapshot,
               query_text_hash, normalized_text_hash, query_kind_snapshot,
               query_cluster_key, source_lineage_hash, brand_scope_snapshot,
               coverage_role_snapshot, topic_cluster_snapshot, funnel_snapshot
           ) VALUES (%s, %s, %s, %s, %s, %s, 1, 'browser-integration', %s, %s,
                     %s, 'recommendation', 'browser-integration', %s, 'brand',
                     'product_fit', 'browser-integration', 'consideration')""",
        (
            question_id,
            seeded["project"],
            campaign_id,
            question_set_id,
            generated_job,
            uuid4(),
            text,
            text_hash,
            canonical_hash({"normalized": text.casefold()}),
            canonical_hash({"source": str(question_id)}),
        ),
    )
    connection.execute("SET LOCAL session_replication_role = origin")
    return question_set_id, question_id, text_hash


def _database_url(admin_url: str, database_name: str) -> str:
    parsed = urlsplit(admin_url)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
