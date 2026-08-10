"""Admin control plane for Browser Capture releases, egress, and profiles."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4, uuid5

from psycopg import Error as PsycopgError
from psycopg.types.json import Jsonb

from geo_core.browser_capture.domain import BrowserCaptureError
from geo_core.browser_capture.lokiproxy import (
    CREATE_ENDPOINT_SQL, ENABLE_ENDPOINT_SQL, SET_ENDPOINT_STATUS_SQL,
    install_pool_profile, reactivate_expired_cooldown, select_pool_candidates,
)
from geo_core.browser_capture.surface_adapters import (
    BUILTIN_BROWSER_RELEASE,
    builtin_surface_adapter,
)
from geo_core.connectors.contracts import canonical_hash
from geo_core.project_scope import set_project_scope


BROWSER_EGRESS_TEST_NAMESPACE = UUID("bb643b3d-e8be-56a9-b7e5-006f30d06fb3")

class BrowserCaptureAdminService:
    def __init__(
        self,
        *,
        connect: Callable[[], Any],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connect = connect
        self._clock = clock

    def create_surface_release(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        platform: str,
        surface: str,
        release_version: str,
        entry_url_template: str,
        allowed_hosts: Sequence[str],
        selectors: Mapping[str, object],
        block_detectors: Mapping[str, object],
        parser_release: str,
        browser_release: str,
        authorization_track: str,
        authorization_status: str,
        authorization_reference: str | None,
        authorization_valid_until: datetime | None,
        terms_version: str,
    ) -> Mapping[str, object]:
        frozen_hosts, frozen_selectors, frozen_blocks = _validate_surface_configuration(
            entry_url_template=entry_url_template,
            allowed_hosts=allowed_hosts,
            selectors=selectors,
            block_detectors=block_detectors,
        )
        if authorization_status == "approved" and (
            not authorization_reference or authorization_valid_until is None
        ):
            raise BrowserCaptureError("Approved Surface authorization needs reference and expiry")
        value = {
            "platform": platform,
            "surface": surface,
            "release_version": release_version,
            "entry_url_template": entry_url_template,
            "allowed_hosts": frozen_hosts,
            "selectors": frozen_selectors,
            "block_detectors": frozen_blocks,
            "parser_release": parser_release,
            "browser_release": browser_release,
            "authorization_track": authorization_track,
            "authorization_status": authorization_status,
            "authorization_reference": authorization_reference,
            "authorization_valid_until": (
                authorization_valid_until.isoformat() if authorization_valid_until else None
            ),
            "terms_version": terms_version,
        }
        now, release_id = self._clock(), uuid4()
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """INSERT INTO browser_surface_releases(
                       id, project_id, platform, surface, release_version,
                       entry_url_template, allowed_hosts, selectors, block_detectors,
                       parser_release, browser_release, authorization_track,
                       authorization_status, authorization_reference,
                       authorization_valid_until, terms_version, release_hash,
                       status, created_by, created_at
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                             %s, %s, %s, %s, %s, %s, 'draft', %s, %s)
                   ON CONFLICT (project_id, surface, release_version) DO NOTHING
                   RETURNING *""",
                (
                    release_id, project_id, platform, surface, release_version,
                    entry_url_template, frozen_hosts, Jsonb(frozen_selectors),
                    Jsonb(frozen_blocks), parser_release, browser_release,
                    authorization_track, authorization_status, authorization_reference,
                    authorization_valid_until, terms_version, canonical_hash(value),
                    actor_id, now,
                ),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    """SELECT * FROM browser_surface_releases
                        WHERE project_id = %s AND surface = %s AND release_version = %s""",
                    (project_id, surface, release_version),
                ).fetchone()
                if row is None or row["release_hash"] != canonical_hash(value):
                    raise BrowserCaptureError(
                        "Surface release version was reused with different content"
                    )
        return dict(row)

    def install_builtin_surface_release(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        surface: str,
    ) -> Mapping[str, object]:
        adapter = builtin_surface_adapter(surface)
        release = self.create_surface_release(
            project_id=project_id,
            actor_id=actor_id,
            platform=adapter.platform,
            surface=adapter.surface,
            release_version=adapter.release_version,
            entry_url_template=adapter.entry_url_template,
            allowed_hosts=adapter.allowed_hosts,
            selectors=adapter.selectors(),
            block_detectors=dict(adapter.block_detectors),
            parser_release=adapter.parser_release,
            browser_release=BUILTIN_BROWSER_RELEASE,
            authorization_track="A",
            authorization_status="approved",
            authorization_reference=f"owner-enabled:{adapter.key}",
            authorization_valid_until=self._clock() + timedelta(days=365),
            terms_version=f"consumer-public-surface:{adapter.release_version}",
        )
        return self.enable_surface_release(
            project_id=project_id,
            release_id=UUID(str(release["id"])),
            actor_id=actor_id,
        )

    def enable_surface_release(
        self, *, project_id: UUID, release_id: UUID, actor_id: UUID
    ) -> Mapping[str, object]:
        now = self._clock()
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """UPDATE browser_surface_releases
                      SET status = 'approved', approved_by = %s, approved_at = %s
                    WHERE project_id = %s AND id = %s
                      AND status IN ('draft', 'approved')
                      AND authorization_status = 'approved'
                      AND authorization_valid_until > %s
                   RETURNING *""",
                (actor_id, now, project_id, release_id, now),
            ).fetchone()
        if row is None:
            raise BrowserCaptureError(
                "Consumer Surface cannot be enabled because its release or terms are stale"
            )
        return dict(row)


    def approve_surface_release(
        self, *, project_id: UUID, release_id: UUID, reviewer_id: UUID
    ) -> Mapping[str, object]:
        now = self._clock()
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """UPDATE browser_surface_releases
                      SET status = 'approved', approved_by = %s, approved_at = %s
                    WHERE project_id = %s AND id = %s AND status = 'draft'
                      AND created_by <> %s AND authorization_status = 'approved'
                      AND authorization_valid_until > %s
                   RETURNING *""",
                (reviewer_id, now, project_id, release_id, reviewer_id, now),
            ).fetchone()
        if row is None:
            raise BrowserCaptureError(
                "Surface Release needs current approved authorization and a different reviewer"
            )
        return dict(row)

    def retire_surface_release(
        self, *, project_id: UUID, release_id: UUID
    ) -> Mapping[str, object]:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """UPDATE browser_surface_releases
                      SET status = 'retired'
                    WHERE project_id = %s AND id = %s
                      AND status IN ('approved', 'suspended')
                   RETURNING *""",
                (project_id, release_id),
            ).fetchone()
        if row is None:
            raise BrowserCaptureError("Only an approved or suspended Surface Release can be retired")
        return dict(row)

    def create_egress_endpoint(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        name: str,
        protocol: str,
        endpoint_host: str,
        endpoint_port: int,
        secret_reference_id: UUID,
        secret_purpose: str,
        secret_version: int,
        expected_region: str | None,
        network_type: str,
        sticky_mode: str,
        egress_policy_version: str,
        egress_cohort_key: str,
        provider: str = "manual",
        pool_product: str = "manual",
        session_ttl_seconds: int = 600,
        max_concurrency: int = 1,
    ) -> Mapping[str, object]:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                CREATE_ENDPOINT_SQL,
                (
                    uuid4(), project_id, name.strip(), protocol, endpoint_host.strip(),
                    endpoint_port, secret_reference_id, secret_purpose, secret_version,
                    expected_region, network_type, sticky_mode, egress_policy_version,
                    egress_cohort_key, provider, pool_product, session_ttl_seconds,
                    max_concurrency, actor_id, self._clock(),
                ),
            ).fetchone()
        return dict(row)

    def approve_egress_endpoint(
        self, *, project_id: UUID, endpoint_id: UUID, reviewer_id: UUID
    ) -> Mapping[str, object]:
        now = self._clock()
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """UPDATE browser_egress_endpoints
                      SET status = 'approved', approved_by = %s, approved_at = %s
                    WHERE project_id = %s AND id = %s AND status = 'draft'
                      AND created_by <> %s
                      AND EXISTS (
                        SELECT 1 FROM secret_versions secret
                         WHERE secret.reference_id = browser_egress_endpoints.secret_reference_id
                           AND secret.project_id = browser_egress_endpoints.project_id
                           AND secret.purpose = browser_egress_endpoints.secret_purpose
                           AND secret.version = browser_egress_endpoints.secret_version
                           AND secret.status = 'active'
                      ) RETURNING *""",
                (reviewer_id, now, project_id, endpoint_id, reviewer_id),
            ).fetchone()
        if row is None:
            raise BrowserCaptureError(
                "Egress Endpoint requires a different reviewer and active exact Secret version"
            )
        return dict(row)

    def install_egress_endpoint(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        name: str,
        protocol: str,
        endpoint_host: str,
        endpoint_port: int,
        secret_reference_id: UUID,
        secret_purpose: str,
        secret_version: int,
        expected_region: str | None,
        network_type: str,
        egress_policy_version: str,
        egress_cohort_key: str,
        provider: str = "manual",
        pool_product: str = "manual",
        session_ttl_seconds: int = 600,
        max_concurrency: int = 1,
    ) -> Mapping[str, object]:
        if provider != "lokiproxy":
            raise BrowserCaptureError("Only LokiProxy pool profiles use the install command")
        return install_pool_profile(
            connect=self._connect, project_id=project_id, actor_id=actor_id, name=name,
            protocol=protocol, endpoint_host=endpoint_host, endpoint_port=endpoint_port,
            secret_reference_id=secret_reference_id, secret_purpose=secret_purpose,
            secret_version=secret_version, expected_region=expected_region,
            network_type=network_type, egress_policy_version=egress_policy_version,
            egress_cohort_key=egress_cohort_key, pool_product=pool_product,
            session_ttl_seconds=session_ttl_seconds, max_concurrency=max_concurrency,
            activated_at=self._clock(),
        )

    def enable_egress_endpoint(
        self, *, project_id: UUID, endpoint_id: UUID, actor_id: UUID
    ) -> Mapping[str, object]:
        now = self._clock()
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                ENABLE_ENDPOINT_SQL,
                (actor_id, now, project_id, endpoint_id),
            ).fetchone()
        if row is None:
            raise BrowserCaptureError(
                "AU proxy cannot be enabled because its exact Secret version is not active"
            )
        return dict(row)

    def set_egress_endpoint_status(
        self, *, project_id: UUID, endpoint_id: UUID, status: str
    ) -> Mapping[str, object]:
        if status not in {"approved", "disabled"}:
            raise BrowserCaptureError("Egress status must be approved or disabled")
        now = self._clock()
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                SET_ENDPOINT_STATUS_SQL,
                (
                    status, status, now, status, status, status,
                    project_id, endpoint_id, status, status,
                ),
            ).fetchone()
        if row is None:
            raise BrowserCaptureError(
                "Egress status transition failed or its exact Secret version is not active"
            )
        return dict(row)

    def test_egress_endpoint(
        self, *, project_id: UUID, actor_id: UUID, endpoint_id: UUID,
        idempotency_key: str,
    ) -> Mapping[str, object]:
        key = idempotency_key.strip()
        if not key or len(key) > 240:
            raise BrowserCaptureError("Egress test needs an idempotency key")
        test_id = uuid5(BROWSER_EGRESS_TEST_NAMESPACE, f"{project_id}:{key}")
        try:
            with self._connect() as connection:
                set_project_scope(connection, project_id)
                reactivate_expired_cooldown(
                    connection, project_id=project_id, endpoint_id=endpoint_id,
                    now=self._clock(),
                )
                row = connection.execute(
                    """SELECT * FROM geo_enqueue_browser_egress_test(
                           %s, %s, %s, %s, %s
                       )""",
                    (project_id, test_id, endpoint_id, actor_id, self._clock()),
                ).fetchone()
        except PsycopgError as error:
            reason = str(error).splitlines()[0].strip()
            raise BrowserCaptureError(reason or "Browser Egress test admission failed") from error
        if row is None:
            raise BrowserCaptureError("Browser Egress test returned no result")
        return dict(row)

    def create_profile(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        version: str,
        browser_release: str,
        device_class: str,
        viewport: Mapping[str, object],
        timezone: str,
        geolocation: Mapping[str, object] | None,
        location_permission: bool,
        safe_search: str,
        account_cohort: str,
        storage_secret_reference_id: UUID | None = None,
        storage_secret_purpose: str | None = None,
        storage_secret_version: int | None = None,
    ) -> Mapping[str, object]:
        value = {
            "version": version, "browser_release": browser_release,
            "device_class": device_class, "viewport": dict(viewport), "locale": "en-AU",
            "timezone": timezone, "geolocation": dict(geolocation) if geolocation else None,
            "location_permission": location_permission, "safe_search": safe_search,
            "account_cohort": account_cohort,
            "storage_secret_reference_id": (
                str(storage_secret_reference_id) if storage_secret_reference_id else None
            ),
            "storage_secret_purpose": storage_secret_purpose,
            "storage_secret_version": storage_secret_version,
        }
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """INSERT INTO browser_profile_versions(
                       id, project_id, version, browser_release, device_class, viewport,
                       locale, timezone, geolocation, location_permission, safe_search,
                       account_cohort, storage_secret_reference_id, storage_secret_purpose,
                       storage_secret_version, profile_hash, status, created_by, created_at
                   ) VALUES (%s, %s, %s, %s, %s, %s, 'en-AU', %s, %s, %s, %s,
                             %s, %s, %s, %s, %s, 'draft', %s, %s) RETURNING *""",
                (
                    uuid4(), project_id, version, browser_release, device_class,
                    Jsonb(dict(viewport)), timezone,
                    Jsonb(dict(geolocation)) if geolocation else None,
                    location_permission, safe_search, account_cohort,
                    storage_secret_reference_id, storage_secret_purpose,
                    storage_secret_version, canonical_hash(value), actor_id, self._clock(),
                ),
            ).fetchone()
        return dict(row)

    def install_anonymous_profile(
        self, *, project_id: UUID, actor_id: UUID
    ) -> Mapping[str, object]:
        version = "au-anonymous-desktop-2026-08-07.1"
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            existing = connection.execute(
                """SELECT * FROM browser_profile_versions
                    WHERE project_id = %s AND version = %s""",
                (project_id, version),
            ).fetchone()
        profile = dict(existing) if existing is not None else self.create_profile(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            browser_release=BUILTIN_BROWSER_RELEASE,
            device_class="desktop",
            viewport={"width": 1440, "height": 1000},
            timezone="Australia/Sydney",
            geolocation=None,
            location_permission=False,
            safe_search="moderate",
            account_cohort="clean_anonymous",
        )
        return self.enable_profile(
            project_id=project_id,
            profile_id=UUID(str(profile["id"])),
            actor_id=actor_id,
        )

    def install_session_profile(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        storage_secret_reference_id: UUID,
        storage_secret_version: int,
    ) -> Mapping[str, object]:
        version = (
            f"au-managed-session-{str(storage_secret_reference_id)[:8]}-"
            f"v{storage_secret_version}"
        )
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            existing = connection.execute(
                """SELECT * FROM browser_profile_versions
                    WHERE project_id = %s AND version = %s""",
                (project_id, version),
            ).fetchone()
        profile = dict(existing) if existing is not None else self.create_profile(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            browser_release=BUILTIN_BROWSER_RELEASE,
            device_class="desktop",
            viewport={"width": 1440, "height": 1000},
            timezone="Australia/Sydney",
            geolocation=None,
            location_permission=False,
            safe_search="moderate",
            account_cohort="managed_test_account",
            storage_secret_reference_id=storage_secret_reference_id,
            storage_secret_purpose="browser_session.storage_state",
            storage_secret_version=storage_secret_version,
        )
        return self.enable_profile(
            project_id=project_id,
            profile_id=UUID(str(profile["id"])),
            actor_id=actor_id,
        )

    def enable_profile(
        self, *, project_id: UUID, profile_id: UUID, actor_id: UUID
    ) -> Mapping[str, object]:
        now = self._clock()
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """UPDATE browser_profile_versions
                      SET status = 'approved', approved_by = %s, approved_at = %s
                    WHERE project_id = %s AND id = %s
                      AND status IN ('draft', 'approved')
                   RETURNING *""",
                (actor_id, now, project_id, profile_id),
            ).fetchone()
        if row is None:
            raise BrowserCaptureError("Browser Profile cannot be enabled")
        return dict(row)

    def bootstrap_builtin_surfaces(
        self, *, project_id: UUID, actor_id: UUID, surfaces: Sequence[str]
    ) -> Mapping[str, object]:
        releases = [
            self.install_builtin_surface_release(
                project_id=project_id, actor_id=actor_id, surface=surface
            )
            for surface in surfaces
        ]
        profile = self.install_anonymous_profile(project_id=project_id, actor_id=actor_id)
        return {"surface_releases": releases, "profile": profile}

    def readiness(self, *, project_id: UUID) -> Mapping[str, object]:
        inventory = self.inventory(project_id=project_id)
        egress_endpoints = cast(
            list[Mapping[str, object]], inventory["egress_endpoints"]
        )
        egress_tests = cast(list[Mapping[str, object]], inventory["egress_tests"])
        profiles = cast(list[Mapping[str, object]], inventory["profiles"])
        surface_releases = cast(
            list[Mapping[str, object]], inventory["surface_releases"]
        )
        approved_endpoints, ready_endpoints = select_pool_candidates(egress_endpoints)
        tested_endpoint_ids = {
            str(item["endpoint_id"])
            for item in egress_tests
            if item["status"] == "succeeded" and item.get("eligible") is True
        }
        approved_profiles = [
            item for item in profiles if item["status"] == "approved"
        ]
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            captured_by_release = {
                str(row["surface_release_id"]): int(row["captured_count"])
                for row in connection.execute(
                    """SELECT surface_release_id, count(*) AS captured_count
                         FROM browser_parsed_observations
                        WHERE project_id = %s
                          AND result_class = 'captured'
                          AND eligible
                        GROUP BY surface_release_id""",
                    (project_id,),
                ).fetchall()
            }
        items = []
        for surface in (
            "google_ai_overviews",
            "google_ai_mode",
            "bing_copilot",
        ):
            releases = [
                item for item in surface_releases if item["surface"] == surface
            ]
            release = releases[0] if releases else None
            captured_count = (
                captured_by_release.get(str(release["id"]), 0) if release else 0
            )
            blocking_reasons: list[str] = []
            if release is None:
                blocking_reasons.append("needs_adapter")
            elif release["status"] == "suspended":
                blocking_reasons.append("adapter_drifted")
            elif release["status"] != "approved":
                blocking_reasons.append("adapter_not_enabled")
            if not approved_endpoints:
                blocking_reasons.append("needs_au_egress")
            elif not ready_endpoints or not any(
                str(item["id"]) in tested_endpoint_ids for item in ready_endpoints
            ):
                blocking_reasons.append("needs_egress_test")
            if not approved_profiles:
                blocking_reasons.append("needs_browser_profile")
            state = "blocked" if blocking_reasons else "ready"
            if not blocking_reasons and captured_count >= 3:
                state = "live_verified"
            if not blocking_reasons and captured_count >= 20:
                state = "fidelity_accepted"
            items.append(
                {
                    "surface": surface,
                    "state": state,
                    "blocking_reasons": blocking_reasons,
                    "surface_release_id": release["id"] if release else None,
                    "release_version": release["release_version"] if release else None,
                    "profile_version_id": approved_profiles[0]["id"] if approved_profiles else None,
                    "egress_endpoint_id": ready_endpoints[0]["id"] if ready_endpoints else None,
                    "captured_count": captured_count,
                }
            )
        return {"items": items}

    def approve_profile(
        self, *, project_id: UUID, profile_id: UUID, reviewer_id: UUID
    ) -> Mapping[str, object]:
        now = self._clock()
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """UPDATE browser_profile_versions
                      SET status = 'approved', approved_by = %s, approved_at = %s
                    WHERE project_id = %s AND id = %s AND status = 'draft'
                      AND created_by <> %s RETURNING *""",
                (reviewer_id, now, project_id, profile_id, reviewer_id),
            ).fetchone()
        if row is None:
            raise BrowserCaptureError("Browser Profile requires a different reviewer")
        return dict(row)

    def inventory(self, *, project_id: UUID) -> Mapping[str, object]:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            tables = {
                "surface_releases": ("browser_surface_releases", "created_at"),
                "egress_endpoints": ("browser_egress_endpoints", "created_at"),
                "profiles": ("browser_profile_versions", "created_at"),
                "egress_tests": ("browser_egress_tests", "requested_at"),
                "drift_events": ("browser_surface_drift_events", "detected_at"),
                "sessions": ("browser_capture_sessions", "started_at"),
            }
            inventory = {
                key: [dict(row) for row in connection.execute(
                    f"SELECT * FROM {table} WHERE project_id = %s ORDER BY {order_by} DESC",
                    (project_id,),
                ).fetchall()]
                for key, (table, order_by) in tables.items()
            }
            inventory["tasks"] = [
                dict(row)
                for row in connection.execute(
                    """SELECT task.id, task.run_id, task.question_id, task.repetition,
                              task.status, task.version, run.status AS run_status,
                              suite.payload->'suite'->>'adapter_release_id'
                                  AS surface_release_id,
                              suite.payload->'suite'->>'route_policy_id'
                                  AS egress_endpoint_id,
                              suite.payload->'suite'->>'model_release_id'
                                  AS profile_version_id,
                              attempt.id AS attempt_id,
                              attempt.status AS attempt_status,
                              attempt.durable_job_id
                         FROM workflow_c_sampling_tasks task
                         JOIN workflow_c_sampling_runs run
                           ON run.project_id = task.project_id AND run.id = task.run_id
                         JOIN workflow_c_sampling_suites suite
                           ON suite.project_id = task.project_id AND suite.id = task.suite_id
                         LEFT JOIN workflow_c_sampling_attempts attempt
                           ON attempt.project_id = task.project_id
                          AND attempt.task_id = task.id
                        WHERE task.project_id = %s
                          AND task.capture_method = 'automated_ui'
                        ORDER BY task.created_at DESC, task.repetition""",
                    (project_id,),
                ).fetchall()
            ]
            return inventory

    def register_sampling_runtime_option(
        self,
        *,
        project_id: UUID,
        surface_release_id: UUID,
        egress_endpoint_id: UUID,
        profile_version_id: UUID,
    ) -> Mapping[str, object]:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT * FROM geo_register_browser_sampling_runtime_option(
                       %s, %s, %s, %s, %s
                   )""",
                (
                    project_id, surface_release_id, egress_endpoint_id,
                    profile_version_id, self._clock(),
                ),
            ).fetchone()
        if row is None:
            raise BrowserCaptureError("Browser Sampling runtime option was not registered")
        return dict(row)

    def sampling_input_material(
        self,
        *,
        project_id: UUID,
        question_set_id: UUID,
        admission_policy_id: UUID,
        surface_release_id: UUID,
        egress_endpoint_id: UUID,
        profile_version_id: UUID,
    ) -> Mapping[str, object]:
        now = self._clock()
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            option = self.register_sampling_runtime_option(
                project_id=project_id,
                surface_release_id=surface_release_id,
                egress_endpoint_id=egress_endpoint_id,
                profile_version_id=profile_version_id,
            )
            policy = connection.execute(
                """SELECT * FROM workflow_c_sampling_admission_policies
                    WHERE project_id = %s AND id = %s AND status = 'approved'
                      AND effective_authorization_state = 'approved'
                      AND valid_until > %s""",
                (project_id, admission_policy_id, now),
            ).fetchone()
            surface = connection.execute(
                """SELECT * FROM browser_surface_releases
                    WHERE project_id = %s AND id = %s AND status = 'approved'""",
                (project_id, surface_release_id),
            ).fetchone()
            endpoint = connection.execute(
                """SELECT * FROM browser_egress_endpoints
                    WHERE project_id = %s AND id = %s AND status = 'approved'
                      AND provider = 'lokiproxy' AND health_status = 'healthy'
                      AND cooldown_until IS NULL""",
                (project_id, egress_endpoint_id),
            ).fetchone()
            profile = connection.execute(
                """SELECT * FROM browser_profile_versions
                    WHERE project_id = %s AND id = %s AND status = 'approved'""",
                (project_id, profile_version_id),
            ).fetchone()
            question_set = connection.execute(
                """SELECT * FROM knowledge_question_sets
                    WHERE project_id = %s AND id = %s AND status = 'frozen'""",
                (project_id, question_set_id),
            ).fetchone()
            questions = connection.execute(
                """SELECT id, query_text_hash FROM knowledge_question_set_items
                    WHERE project_id = %s AND question_set_id = %s ORDER BY ordinal""",
                (project_id, question_set_id),
            ).fetchall()
        if any(item is None for item in (policy, surface, endpoint, profile, question_set)):
            raise BrowserCaptureError(
                "Approved authorization and frozen Browser/Sampling inputs are required"
            )
        if not questions:
            raise BrowserCaptureError("Frozen Question Set has no questions")
        if (
            policy["capture_method"] != "automated_ui"
            or policy["platform"] != surface["platform"]
            or policy["adapter_release"] != option["adapter_release"]
            or policy["location_evidence_hash"] != option["location_evidence_hash"]
        ):
            raise BrowserCaptureError("Sampling policy does not match the frozen Browser option")
        return {
            "option": option, "policy": dict(policy), "surface": dict(surface),
            "endpoint": dict(endpoint), "profile": dict(profile),
            "question_set": dict(question_set),
            "questions": [dict(item) for item in questions],
        }


_REQUIRED_SURFACE_SELECTORS = frozenset(
    {"query_input", "page_complete", "surface_marker", "answer", "citations", "page_location"}
)
_OPTIONAL_SURFACE_SELECTORS = frozenset(
    {
        "adapter_key",
        "block_text_patterns",
        "completion_mode",
        "navigation_mode",
        "ready_timeout_ms",
    }
)
_BLOCK_DETECTORS = frozenset({"consent", "login", "captcha", "rate_limit", "ban"})


def _validate_surface_configuration(
    *,
    entry_url_template: str,
    allowed_hosts: Sequence[str],
    selectors: Mapping[str, object],
    block_detectors: Mapping[str, object],
) -> tuple[list[str], dict[str, object], dict[str, str]]:
    hosts = sorted({item.strip().casefold() for item in allowed_hosts if item.strip()})
    if not hosts or any("/" in item or ":" in item or "@" in item for item in hosts):
        raise BrowserCaptureError("Surface allowed_hosts must contain plain hostnames")
    parsed = urlsplit(entry_url_template)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname.casefold() not in hosts
        or parsed.username
        or parsed.password
    ):
        raise BrowserCaptureError("Surface entry URL must use HTTPS and an allowed host")
    selector_keys = set(selectors)
    missing = sorted(_REQUIRED_SURFACE_SELECTORS - selector_keys)
    unknown = sorted(selector_keys - _REQUIRED_SURFACE_SELECTORS - _OPTIONAL_SURFACE_SELECTORS)
    if missing or unknown:
        raise BrowserCaptureError(
            f"Surface selectors are invalid (missing={missing}, unknown={unknown})"
        )
    frozen_selectors: dict[str, object] = {}
    for name in sorted(_REQUIRED_SURFACE_SELECTORS):
        value = selectors[name]
        if not isinstance(value, str) or not value.strip() or len(value) > 1_000:
            raise BrowserCaptureError(f"Surface selector {name} must be a non-empty string")
        frozen_selectors[name] = value.strip()
    timeout = selectors.get("ready_timeout_ms", 45_000)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1_000 <= timeout <= 180_000:
        raise BrowserCaptureError("Surface ready_timeout_ms must be between 1000 and 180000")
    frozen_selectors["ready_timeout_ms"] = timeout
    adapter_key = selectors.get("adapter_key")
    if adapter_key is not None:
        if not isinstance(adapter_key, str) or not adapter_key.strip() or len(adapter_key) > 200:
            raise BrowserCaptureError("Surface adapter_key is invalid")
        frozen_selectors["adapter_key"] = adapter_key.strip()
    navigation_mode = selectors.get("navigation_mode", "form_submit")
    if navigation_mode not in {"form_submit", "direct_query"}:
        raise BrowserCaptureError("Surface navigation_mode is invalid")
    if navigation_mode == "direct_query" and "{query}" not in entry_url_template:
        raise BrowserCaptureError("Direct-query Surface entry URL must contain {query}")
    frozen_selectors["navigation_mode"] = navigation_mode
    completion_mode = selectors.get("completion_mode", "document_ready")
    if completion_mode not in {"document_ready", "stable_answer"}:
        raise BrowserCaptureError("Surface completion_mode is invalid")
    frozen_selectors["completion_mode"] = completion_mode
    text_patterns = selectors.get("block_text_patterns", {})
    if not isinstance(text_patterns, Mapping) or set(text_patterns) - _BLOCK_DETECTORS:
        raise BrowserCaptureError("Surface block_text_patterns are invalid")
    frozen_patterns: dict[str, list[str]] = {}
    for name, values in text_patterns.items():
        if not isinstance(values, list) or not values or any(
            not isinstance(value, str) or not value.strip() or len(value) > 500
            for value in values
        ):
            raise BrowserCaptureError(f"Surface block text patterns for {name} are invalid")
        frozen_patterns[str(name)] = [value.strip().casefold() for value in values]
    frozen_selectors["block_text_patterns"] = frozen_patterns
    unknown_blocks = sorted(set(block_detectors) - _BLOCK_DETECTORS)
    if unknown_blocks:
        raise BrowserCaptureError(f"Unsupported Surface block detectors: {unknown_blocks}")
    frozen_blocks = {}
    for name, value in block_detectors.items():
        if not isinstance(value, str) or not value.strip() or len(value) > 1_000:
            raise BrowserCaptureError(f"Surface block detector {name} is invalid")
        frozen_blocks[name] = value.strip()
    return hosts, frozen_selectors, frozen_blocks


__all__ = ["BrowserCaptureAdminService"]
