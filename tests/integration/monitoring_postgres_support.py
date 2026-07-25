"""Fixtures and isolated object-store support for monitoring integration tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import os
import subprocess
import time
from uuid import UUID, uuid4

import psycopg
from redis import Redis

from geo_core.monitoring.domain import (
    CitationDraft,
    MeasurementWindow,
    ObservationDraft,
    ResultStatus,
    VerificationStatus,
)
from geo_core.monitoring.source_contract import (
    CaptureMethod,
    ClientKind,
    ModelIdentity,
    ModelIdentityState,
    ObservationDevice,
    ObservationPlatform,
    ObservationRunParameters,
    ObservationSource,
    ObservationSurface,
    RawEvidence,
    RawEvidenceKind,
    SearchMode,
    SurfaceKind,
)
from geo_core.object_store import ObjectStoreError, S3CompatibleObjectStore


ADMIN_URL = os.getenv("GEO_ACCESS_TEST_ADMIN_DATABASE_URL", "").strip()
MINIO_IMAGE = "minio/minio:RELEASE.2025-01-20T14-49-07Z"
VALKEY_IMAGE = "valkey/valkey:8.0.2-alpine"


def draft(
    query_id: UUID,
    sample_index: int,
    *,
    eligible: bool,
    verified: bool,
    source: ObservationSource,
    citation: CitationDraft | None = None,
) -> ObservationDraft:
    evidence = source.raw_evidence
    return ObservationDraft(
        monitoring_query_id=query_id,
        measurement_window=MeasurementWindow.T28,
        sample_index=sample_index,
        result_status=ResultStatus.SUCCEEDED,
        requested_eligible=eligible,
        eligible=eligible,
        ineligible_reasons=() if eligible else ("manual_exclusion",),
        url_verification_status=(
            VerificationStatus.PASSED if verified else VerificationStatus.FAILED
        ),
        recommendation_present=True,
        primary_product_mentioned=True,
        competitor_mentioned=False,
        raw_answer=evidence.answer,
        raw_result=dict(evidence.inline_response or {}),
        citations=(citation,) if citation else (),
        artifact_uri=evidence.artifact_uri,
        artifact_hash=evidence.artifact_hash,
        configured_model=source.configured_model.value,
        provider_reported_model=source.reported_model.value,
        ui_surface=source.surface.value,
        ui_metadata={"locale": "en-AU"},
        confounding_factors=(),
        observed_at=datetime.now(UTC),
        source=source,
    )


def source(method: CaptureMethod) -> ObservationSource:
    if method == CaptureMethod.MANUAL_UI:
        platform = ObservationPlatform.OPENAI
        surface = ObservationSurface.CHATGPT_SEARCH
        surface_kind = SurfaceKind.CONSUMER_UI
        device = ObservationDevice.DESKTOP
        client_kind = ClientKind.BROWSER
        search_mode = SearchMode.LIVE_WEB
        adapter_name = adapter_version = provider_request_id = None
        evidence = RawEvidence(RawEvidenceKind.ANSWER, answer="internal raw answer")
    elif method == CaptureMethod.PROVIDER_API:
        platform = ObservationPlatform.OPENAI
        surface = ObservationSurface.OPENAI_API
        surface_kind = SurfaceKind.PROVIDER_API
        device = ObservationDevice.API
        client_kind = ClientKind.API
        search_mode = SearchMode.LIVE_WEB
        adapter_name, adapter_version, provider_request_id = "openai", "1.0", "req-1"
        evidence = RawEvidence(
            RawEvidenceKind.INLINE_RESPONSE,
            inline_response={"answer": "provider raw response", "rank": 1},
        )
    elif method == CaptureMethod.PROXY_GROUNDED_API:
        platform = ObservationPlatform.MICROSOFT
        surface = ObservationSurface.MICROSOFT_FOUNDRY_BING_GROUNDING
        surface_kind = SurfaceKind.GROUNDED_PROXY
        device = ObservationDevice.API
        client_kind = ClientKind.API
        search_mode = SearchMode.GROUNDED_WEB
        adapter_name, adapter_version, provider_request_id = "foundry", "1.0", "req-2"
        evidence = RawEvidence(RawEvidenceKind.ANSWER, answer="proxy grounded answer")
    else:
        raise AssertionError(method)
    return ObservationSource(
        capture_method=method,
        platform=platform,
        surface=surface,
        surface_kind=surface_kind,
        platform_detail=None,
        surface_detail=None,
        configured_model=ModelIdentity(ModelIdentityState.DISCLOSED, "deepseek-chat"),
        reported_model=ModelIdentity(ModelIdentityState.NOT_DISCLOSED),
        run=ObservationRunParameters(
            engine=platform.value,
            locale="en-AU",
            region="AU",
            language="en",
            device=device,
            client_kind=client_kind,
            search_enabled=True,
            search_mode=search_mode,
            prompt_text="best robot vacuum",
            adapter_name=adapter_name,
            adapter_version=adapter_version,
            provider_request_id=provider_request_id,
        ),
        raw_evidence=evidence,
        citations_captured=True,
    )


def synthetic_source(project_id: UUID) -> ObservationSource:
    return ObservationSource(
        capture_method=CaptureMethod.SYNTHETIC,
        platform=ObservationPlatform.OTHER,
        surface=ObservationSurface.INTERNAL_BENCHMARK,
        surface_kind=SurfaceKind.INTERNAL_BENCHMARK,
        platform_detail="controlled-adapter",
        surface_detail=None,
        configured_model=ModelIdentity(ModelIdentityState.DISCLOSED, "deepseek-chat"),
        reported_model=ModelIdentity(ModelIdentityState.NOT_DISCLOSED),
        run=ObservationRunParameters(
            engine="controlled",
            locale="en-AU",
            region="AU",
            language="en",
            device=ObservationDevice.INTERNAL_WORKER,
            client_kind=ClientKind.INTERNAL_WORKER,
            search_enabled=False,
            search_mode=SearchMode.DISABLED,
            prompt_text="best robot vacuum",
            adapter_name="controlled-benchmark",
            adapter_version="1.0",
        ),
        raw_evidence=RawEvidence(
            RawEvidenceKind.ARTIFACT,
            artifact_uri=(f"s3://geo-artifacts/content-simulations/{project_id}/result.json"),
            artifact_hash="b" * 64,
            artifact_verified=True,
        ),
        citations_captured=True,
        source_job_id=uuid4(),
        model_call_log_id=uuid4(),
        test_only=True,
        publication_eligible=False,
    )


def seed(**values: object) -> None:
    with psycopg.connect(ADMIN_URL) as connection:
        connection.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, %s)",
            (values["tenant_id"], f"Monitoring {values['marker']}"),
        )
        connection.execute(
            "INSERT INTO identities (id, issuer, subject) VALUES (%s, 'test', %s)",
            (values["identity_id"], f"monitor-{values['marker']}"),
        )
        for project_id, name in (
            (values["project_id"], "Owned"),
            (values["foreign_project_id"], "Foreign"),
        ):
            connection.execute(
                "INSERT INTO projects (id, tenant_id, name) VALUES (%s, %s, %s)",
                (project_id, values["tenant_id"], f"{name} {values['marker']}"),
            )
        connection.execute(
            """INSERT INTO project_memberships (tenant_id, project_id, identity_id, role)
               VALUES (%s, %s, %s, 'owner')""",
            (values["tenant_id"], values["project_id"], values["identity_id"]),
        )
        for market_id, project_id, code in (
            (values["market_id"], values["project_id"], "AU"),
            (values["foreign_market_id"], values["foreign_project_id"], "NZ"),
        ):
            connection.execute(
                """INSERT INTO market_profiles
                     (id, project_id, market_code, locale, timezone)
                   VALUES (%s, %s, %s, 'en-AU', 'Australia/Sydney')""",
                (market_id, project_id, code),
            )
        connection.execute(
            """INSERT INTO product_entities
                 (id, project_id, entity_type, canonical_name)
               VALUES (%s, %s, 'product', %s)""",
            (values["product_id"], values["project_id"], f"Product {values['marker']}"),
        )
        for campaign_id, name in (
            (values["campaign_id"], "Campaign"),
            (values["other_campaign_id"], "Other campaign"),
        ):
            connection.execute(
                """INSERT INTO geo_campaigns
                     (id, project_id, market_profile_id, primary_product_entity_id,
                      name, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    campaign_id,
                    values["project_id"],
                    values["market_id"],
                    values["product_id"],
                    f"{name} {values['marker']}",
                    values["identity_id"],
                ),
            )


def seed_campaign_destinations(
    *, project_id: UUID, campaign_id: UUID, identity_id: UUID, marker: str
) -> tuple[str, UUID, UUID, str]:
    qualified_destination, selected_destination = uuid4(), uuid4()
    qualified_opportunity, selected_opportunity = uuid4(), uuid4()
    package_id, package_version_id = uuid4(), uuid4()
    selected_package_id, selected_package_version_id = uuid4(), uuid4()
    request_id, submission_id = uuid4(), uuid4()
    selected_request_id, selected_submission_id = uuid4(), uuid4()
    url = f"https://example.com/{marker}/verified"
    unapproved_url = f"https://example.com/{marker}/outside-approved-snapshot"
    with psycopg.connect(ADMIN_URL) as connection:
        connection.execute("SET LOCAL session_replication_role = 'replica'")
        for destination_id, key, policy in (
            (qualified_destination, f"qualified-{marker}", "approved"),
            (selected_destination, f"selected-{marker}", "unreviewed"),
        ):
            connection.execute(
                """INSERT INTO publication_destinations
                     (id, project_id, publication_channel, destination_key, policy_status,
                      canonical_url, canonical_host, allowed_hosts)
                   VALUES (%s, %s, 'owned_site', %s, %s,
                           'https://example.com/', 'example.com', ARRAY['example.com'])""",
                (destination_id, project_id, key, policy),
            )
        for opportunity_id, destination_id, status in (
            (qualified_opportunity, qualified_destination, "qualified"),
            (selected_opportunity, selected_destination, "identified"),
        ):
            connection.execute(
                """INSERT INTO placement_opportunities
                     (id, project_id, campaign_id, destination_id,
                      opportunity_ref, rationale, status)
                   VALUES (%s, %s, %s, %s, %s, 'test fixture', %s)""",
                (
                    opportunity_id,
                    project_id,
                    campaign_id,
                    destination_id,
                    f"test:{opportunity_id}",
                    status,
                ),
            )
        connection.execute(
            """INSERT INTO placement_packages
                 (id, project_id, opportunity_id, campaign_id, destination_id)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                package_id,
                project_id,
                qualified_opportunity,
                campaign_id,
                qualified_destination,
            ),
        )
        connection.execute(
            """INSERT INTO placement_packages
                 (id, project_id, opportunity_id, campaign_id, destination_id)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                selected_package_id,
                project_id,
                selected_opportunity,
                campaign_id,
                selected_destination,
            ),
        )
        connection.execute(
            """INSERT INTO placement_package_versions
                 (id, project_id, package_id, prompt_bundle_id, version_number,
                  workflow_status, content_json, rendered_text, content_hash,
                  edited_by, edit_reason, campaign_id, opportunity_id, destination_id)
               VALUES (%s, %s, %s, %s, 1, 'approved', '{}'::jsonb,
                       'upstream verified fixture', %s, %s,
                       'monitoring integration fixture', %s, %s, %s)""",
            (
                package_version_id,
                project_id,
                package_id,
                uuid4(),
                "d" * 64,
                identity_id,
                campaign_id,
                qualified_opportunity,
                qualified_destination,
            ),
        )
        connection.execute(
            """INSERT INTO placement_package_versions
                 (id, project_id, package_id, prompt_bundle_id, version_number,
                  workflow_status, content_json, rendered_text, content_hash,
                  edited_by, edit_reason, campaign_id, opportunity_id, destination_id)
               VALUES (%s, %s, %s, %s, 1, 'approved', '{}'::jsonb,
                       'outside approved snapshot fixture', %s, %s,
                       'monitoring integration fixture', %s, %s, %s)""",
            (
                selected_package_version_id,
                project_id,
                selected_package_id,
                uuid4(),
                "f" * 64,
                identity_id,
                campaign_id,
                selected_opportunity,
                selected_destination,
            ),
        )
        connection.execute(
            """INSERT INTO publication_requests
                 (id, project_id, package_version_id, destination_id,
                  idempotency_key, requested_by, status, campaign_id, opportunity_id)
               VALUES (%s, %s, %s, %s, %s, %s, 'published', %s, %s)""",
            (
                request_id,
                project_id,
                package_version_id,
                qualified_destination,
                f"request-{marker}",
                identity_id,
                campaign_id,
                qualified_opportunity,
            ),
        )
        connection.execute(
            """INSERT INTO publication_requests
                 (id, project_id, package_version_id, destination_id,
                  idempotency_key, requested_by, status, campaign_id, opportunity_id)
               VALUES (%s, %s, %s, %s, %s, %s, 'published', %s, %s)""",
            (
                selected_request_id,
                project_id,
                selected_package_version_id,
                selected_destination,
                f"outside-request-{marker}",
                identity_id,
                campaign_id,
                selected_opportunity,
            ),
        )
        connection.execute(
            """INSERT INTO publication_submissions
                 (id, project_id, publication_request_id, submitted_url,
                  idempotency_key, payload_hash, submitted_by,
                  status, submitted_at, verified_at, campaign_id,
                  opportunity_id, destination_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s,
                       'verified', clock_timestamp(), clock_timestamp(), %s, %s, %s)""",
            (
                submission_id,
                project_id,
                request_id,
                url,
                f"monitoring-submission-{marker}",
                "e" * 64,
                identity_id,
                campaign_id,
                qualified_opportunity,
                qualified_destination,
            ),
        )
        connection.execute(
            """INSERT INTO publication_submissions
                 (id, project_id, publication_request_id, submitted_url,
                  idempotency_key, payload_hash, submitted_by,
                  status, submitted_at, verified_at, campaign_id,
                  opportunity_id, destination_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s,
                       'verified', clock_timestamp(), clock_timestamp(), %s, %s, %s)""",
            (
                selected_submission_id,
                project_id,
                selected_request_id,
                unapproved_url,
                f"outside-submission-{marker}",
                "a" * 64,
                identity_id,
                campaign_id,
                selected_opportunity,
                selected_destination,
            ),
        )
        connection.execute("SET LOCAL session_replication_role = 'origin'")
    return url, submission_id, qualified_destination, unapproved_url


def cleanup(tenant_id: UUID, identity_id: UUID) -> None:
    with psycopg.connect(ADMIN_URL) as connection:
        connection.execute("SET LOCAL session_replication_role = 'replica'")
        for table in (
            "monitoring_metric_snapshot_observations",
            "monitoring_official_report_rows",
            "monitoring_official_report_imports",
            "monitoring_reports",
            "monitoring_metric_snapshots",
            "monitoring_observation_citations",
            "monitoring_observations",
            "monitoring_protocol_queries",
            "monitoring_query_suggestions",
            "monitoring_protocols",
            "publication_submissions",
            "publication_requests",
            "placement_package_versions",
            "placement_packages",
            "placement_opportunities",
            "publication_destinations",
            "campaign_monitoring_queries",
            "monitoring_queries",
            "geo_campaigns",
            "product_entities",
            "market_profiles",
            "project_memberships",
        ):
            connection.execute(
                f"""DELETE FROM {table}
                    WHERE project_id IN (SELECT id FROM projects WHERE tenant_id = %s)""",
                (tenant_id,),
            )
        connection.execute("DELETE FROM projects WHERE tenant_id = %s", (tenant_id,))
        connection.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
        connection.execute("SET LOCAL session_replication_role = 'origin'")
        connection.execute("DELETE FROM identities WHERE id = %s", (identity_id,))


@contextmanager
def isolated_minio_store() -> Iterator[S3CompatibleObjectStore]:
    run_id = uuid4().hex[:12]
    name = f"geo-f009-minio-{run_id}"
    access_key = f"f009{run_id}"
    secret_key = f"minio-{uuid4().hex}"
    bucket = f"geo-f009-{run_id}"
    docker_command("info", "--format", "{{.ServerVersion}}", timeout=30)
    try:
        docker_command(
            "run",
            "--detach",
            "--name",
            name,
            "--label",
            "geo.test=f009",
            "--publish",
            "127.0.0.1::9000",
            "-e",
            f"MINIO_ROOT_USER={access_key}",
            "-e",
            f"MINIO_ROOT_PASSWORD={secret_key}",
            MINIO_IMAGE,
            "server",
            "/data",
            "--address",
            ":9000",
        )
        published = docker_command("port", name, "9000/tcp")
        endpoint = f"http://{published.strip()}"
        store = S3CompatibleObjectStore(
            endpoint=endpoint,
            bucket=bucket,
            access_key=access_key,
            secret_key=secret_key,
        )
        deadline = time.monotonic() + 30
        while True:
            try:
                store.ensure_bucket()
                break
            except ObjectStoreError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)
        yield store
    finally:
        docker_command("rm", "--force", name, check=False, timeout=30)


@contextmanager
def isolated_valkey_url() -> Iterator[str]:
    run_id = uuid4().hex[:12]
    name = f"geo-wfc-valkey-{run_id}"
    docker_command("info", "--format", "{{.ServerVersion}}", timeout=30)
    try:
        docker_command(
            "run",
            "--detach",
            "--name",
            name,
            "--label",
            "geo.test=workflow-c",
            "--publish",
            "127.0.0.1::6379",
            VALKEY_IMAGE,
        )
        published = docker_command("port", name, "6379/tcp")
        url = f"redis://{published.strip()}/0"
        client = Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        deadline = time.monotonic() + 30
        try:
            while True:
                try:
                    if client.ping():
                        break
                except Exception:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.25)
            yield url
        finally:
            client.close()
    finally:
        docker_command("rm", "--force", name, check=False, timeout=30)


def docker_command(*arguments: str, check: bool = True, timeout: float = 180) -> str:
    completed = subprocess.run(
        ("docker", *arguments),
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed.stdout.strip()
