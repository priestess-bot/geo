"""Fenced Browser Capture execution from proxy lease to Sampling Observation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hmac
import json
from typing import Any, Protocol
from uuid import UUID, uuid4, uuid5

from psycopg.types.json import Jsonb

from geo_core.browser_capture.artifacts import EncryptedBrowserArtifactWriter
from geo_core.browser_capture.domain import BrowserCaptureError, NetworkType
from geo_core.browser_capture.parsing import SurfaceRelease, parse_capture
from geo_core.browser_capture.playwright_driver import (
    BrowserProfile,
    EgressProbe,
    PlaywrightBrowserDriver,
    ProxyLease,
    SurfaceSelectors,
)
from geo_core.browser_capture.routing import BROWSER_CAPTURE_JOB_KIND
from geo_core.connectors.contracts import canonical_hash
from geo_core.jobs.postgres import LeaseHeartbeat, PostgresDurableJobStore, WorkerLease
from geo_core.project_scope import set_project_scope


BROWSER_OBSERVATION_NAMESPACE = UUID("0ad4d6d8-c23d-5e53-9af7-efc3749d7ac8")


class BrowserProxyCredentialResolver(Protocol):
    def resolve(
        self, *, project_id: UUID, reference_id: UUID, purpose: str, version: int
    ) -> Mapping[str, object]: ...


class BrowserDriver(Protocol):
    def capture(
        self,
        *,
        query: str,
        expected_surface: str,
        proxy: ProxyLease,
        profile: BrowserProfile,
        selectors: SurfaceSelectors,
        probes: tuple[EgressProbe, ...],
        now: datetime | None = None,
    ): ...


@dataclass(frozen=True)
class BrowserCapturePreparation:
    attempt_id: UUID
    spec_hash: str
    question_text: str
    surface: Mapping[str, object]
    endpoint: Mapping[str, object]
    profile: Mapping[str, object]


@dataclass(frozen=True)
class BrowserCaptureExecution:
    preparation: BrowserCapturePreparation
    capture_session_id: UUID
    execution_ordinal: int
    task_version: int
    attempt_version: int


class PostgresBrowserCaptureWorkerRepository:
    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def prepare(self, lease: WorkerLease) -> BrowserCapturePreparation:
        if lease.kind != BROWSER_CAPTURE_JOB_KIND:
            raise BrowserCaptureError("Browser worker received the wrong Job kind")
        with self._connect() as connection:
            set_project_scope(connection, lease.project_id)
            row = connection.execute(
                """SELECT spec.attempt_id, spec.spec_hash, spec.question_text,
                          durable.input_hash, durable.status,
                          to_jsonb(surface_row) AS surface,
                          to_jsonb(endpoint_row) AS endpoint,
                          to_jsonb(profile_row) AS profile
                     FROM browser_capture_job_specs spec
                     JOIN durable_jobs durable
                       ON durable.project_id = spec.project_id AND durable.id = spec.job_id
                     JOIN browser_surface_releases surface_row
                       ON surface_row.project_id = spec.project_id
                      AND surface_row.id = spec.surface_release_id
                     JOIN browser_egress_endpoints endpoint_row
                       ON endpoint_row.project_id = spec.project_id
                      AND endpoint_row.id = spec.egress_endpoint_id
                     JOIN browser_profile_versions profile_row
                       ON profile_row.project_id = spec.project_id
                      AND profile_row.id = spec.profile_version_id
                    WHERE spec.project_id = %s AND spec.job_id = %s""",
                (lease.project_id, lease.job_id),
            ).fetchone()
        if row is None or row["status"] != "running":
            raise BrowserCaptureError("Browser Capture Job state was not found or executable")
        if not hmac.compare_digest(str(row["spec_hash"]), str(row["input_hash"])):
            raise BrowserCaptureError("Browser Capture immutable Job spec changed")
        return BrowserCapturePreparation(
            attempt_id=row["attempt_id"],
            spec_hash=row["spec_hash"],
            question_text=row["question_text"],
            surface=_mapping_value(row["surface"], "Surface Release"),
            endpoint=_mapping_value(row["endpoint"], "Egress Endpoint"),
            profile=_mapping_value(row["profile"], "Browser Profile"),
        )

    def start(
        self,
        lease: WorkerLease,
        *,
        preparation: BrowserCapturePreparation,
        proxy: ProxyLease,
    ) -> BrowserCaptureExecution:
        session_hash = canonical_hash(
            {
                "job_id": str(lease.job_id),
                "attempt_id": str(preparation.attempt_id),
                "fencing_generation": lease.fencing_generation,
                "sticky_lease_hash": proxy.lease_hash,
                "started_at": proxy.started_at.isoformat(),
            }
        )
        with self._connect() as connection:
            set_project_scope(connection, lease.project_id)
            row = connection.execute(
                """SELECT * FROM geo_start_browser_capture_execution(
                       %s, %s, %s, %s, %s, %s, %s, %s, %s
                   )""",
                (
                    lease.project_id,
                    lease.job_id,
                    lease.lease_token,
                    lease.fencing_generation,
                    proxy.lease_id,
                    proxy.lease_hash,
                    proxy.started_at,
                    proxy.expires_at,
                    session_hash,
                ),
            ).fetchone()
        if row is None or not hmac.compare_digest(row["spec_hash"], preparation.spec_hash):
            raise BrowserCaptureError("Browser Capture execution start returned stale lineage")
        if (
            UUID(str(_mapping_value(row["surface"], "Surface Release")["id"]))
            != UUID(str(preparation.surface["id"]))
            or UUID(str(_mapping_value(row["endpoint"], "Egress Endpoint")["id"]))
            != UUID(str(preparation.endpoint["id"]))
            or UUID(str(_mapping_value(row["profile"], "Browser Profile")["id"]))
            != UUID(str(preparation.profile["id"]))
        ):
            raise BrowserCaptureError("Browser Capture resources changed during start")
        return BrowserCaptureExecution(
            preparation=preparation,
            capture_session_id=row["capture_session_id"],
            execution_ordinal=row["execution_ordinal"],
            task_version=row["task_version"],
            attempt_version=row["attempt_version"],
        )

    def assert_browser_runtime(
        self, lease: WorkerLease, *, preparation: BrowserCapturePreparation,
        observed_release: str, detected_at: datetime,
    ) -> None:
        expected = str(preparation.surface.get("browser_release", "")).strip()
        if expected == observed_release:
            return
        with self._connect() as connection:
            set_project_scope(connection, lease.project_id)
            connection.execute(
                "SELECT geo_suspend_browser_surface_for_runtime_drift(%s,%s,%s,%s,%s)",
                (
                    lease.project_id, lease.job_id, preparation.surface["id"],
                    observed_release, detected_at,
                ),
            )
        raise BrowserCaptureError(
            f"Browser runtime drift: Surface requires {expected}, Worker provides {observed_release}"
        )

    def commit(
        self,
        connection: Any,
        *,
        lease: WorkerLease,
        execution: BrowserCaptureExecution,
        capture: Any,
        parsed: Any,
        bundle: Any,
        observed_at: datetime,
    ) -> UUID:
        endpoint = execution.preparation.endpoint
        profile = execution.preparation.profile
        verification = capture.verification
        representative = verification.pre[0]
        ineligible_reasons = (
            [] if parsed.eligible else [f"browser_capture:{parsed.outcome.value}"]
        )
        evidence_status = "complete" if parsed.eligible else "ineligible"
        actual_location = {
            "location_control": "country",
            "location_evidence_hash": verification.verification_hash,
            "requested_country": "AU",
            "requested_region": endpoint.get("expected_region"),
            "requested_locale": profile["locale"],
            "requested_language": "en",
            "effective_country": representative.country,
            "effective_region": representative.region,
            "effective_locale": profile["locale"],
            "effective_language": "en",
        }
        evidence = {
            "schema_version": 1,
            "kind": "automated_ui",
            "raw_artifact": {
                "kind": "raw",
                "manifest_reference": bundle.manifest_uri,
                "manifest_hash": bundle.manifest_hash,
                "content_hash": bundle.dom_hash,
                "governance_policy_hash": canonical_hash(
                    {
                        "classification": "restricted_raw_consumer_surface",
                        "retention_until": bundle.retention_until.isoformat(),
                    }
                ),
            },
            "derived_artifact": {
                "kind": "derived",
                "manifest_reference": bundle.manifest_uri,
                "manifest_hash": bundle.manifest_hash,
                "content_hash": parsed.observation_hash,
                "governance_policy_hash": canonical_hash(
                    {"display": "admin_only", "redistribution": "prohibited"}
                ),
            },
            "derived_summary": f"Consumer surface capture: {parsed.outcome.value}.",
            "evidence_locator": f"{bundle.manifest_uri}#/items/page.html",
            "provider_response_id": None,
            "egress_verification_id": str(verification.id),
            "result_parameters_hash": canonical_hash(
                {
                    "capture_session_id": str(execution.capture_session_id),
                    "surface_release_hash": execution.preparation.surface["release_hash"],
                    "profile_hash": profile["profile_hash"],
                    "egress_policy_version": endpoint["egress_policy_version"],
                    "verification_hash": verification.verification_hash,
                }
            ),
            "storage_decision": "encrypted_restricted",
            "cache_decision": "prohibited",
            "display_decision": "admin_only",
            "redistribution_decision": "prohibited",
            "usage_purpose": "sampling.automated_ui",
            "usage_audience": "internal_worker",
        }
        observation_id = uuid5(
            BROWSER_OBSERVATION_NAMESPACE,
            canonical_hash(
                {
                    "attempt_id": str(execution.preparation.attempt_id),
                    "capture_session_id": str(execution.capture_session_id),
                    "evidence": evidence,
                    "actual_location": actual_location,
                }
            ),
        )
        observation_hash = canonical_hash(
            {
                "project_id": str(lease.project_id),
                "attempt_id": str(execution.preparation.attempt_id),
                "evidence_status": evidence_status,
                "ineligible_reasons": ineligible_reasons,
                "actual_location": actual_location,
                "evidence": evidence,
                "observed_at": observed_at.isoformat(),
            }
        )
        bundle_id = uuid5(BROWSER_OBSERVATION_NAMESPACE, f"bundle:{observation_id}")
        parsed_id = uuid5(BROWSER_OBSERVATION_NAMESPACE, f"parsed:{observation_id}")
        citations = [item.value() for item in parsed.citations]
        page_location = {
            "country": capture.signals.page_country,
            "final_url": capture.signals.final_url,
        }
        row = connection.execute(
            """SELECT geo_commit_browser_capture_execution(
                   %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                   %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                   %s,%s,%s,%s,%s,%s,%s
               ) AS observation_id""",
            (
                lease.project_id,
                lease.job_id,
                lease.lease_token,
                lease.fencing_generation,
                execution.capture_session_id,
                execution.task_version,
                execution.attempt_version,
                verification.id,
                Jsonb([item.safe_value() for item in verification.pre]),
                Jsonb([item.safe_value() for item in verification.post]),
                representative.ip_hash,
                representative.asn,
                representative.country,
                representative.region,
                verification.network_type.value,
                verification.connection_log_reference,
                verification.connection_log_hash,
                verification.verification_hash,
                verification.outcome.value,
                verification.eligible,
                bundle_id,
                bundle.manifest_uri,
                bundle.manifest_hash,
                bundle.screenshot_hash,
                bundle.dom_hash,
                bundle.har_hash,
                capture.signals.final_url,
                canonical_hash({"url": capture.signals.final_url}),
                Jsonb(page_location),
                bundle.encryption_key_reference,
                bundle.retention_until,
                parsed_id,
                parsed.outcome.value,
                parsed.answer_text,
                Jsonb(citations),
                Jsonb(dict(parsed.evidence_locators)),
                execution.preparation.surface["parser_release"],
                parsed.observation_hash,
                parsed.eligible,
                observed_at,
                observation_id,
                observation_hash,
                evidence_status,
                Jsonb(ineligible_reasons),
                Jsonb(actual_location),
                canonical_hash(actual_location),
                Jsonb(evidence),
            ),
        ).fetchone()
        if row is None or row["observation_id"] != observation_id:
            raise BrowserCaptureError("Browser Capture completion returned stale lineage")
        return observation_id


class BrowserCaptureOperation:
    kind = BROWSER_CAPTURE_JOB_KIND

    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        repository: PostgresBrowserCaptureWorkerRepository,
        credentials: BrowserProxyCredentialResolver,
        artifacts: EncryptedBrowserArtifactWriter,
        probes: tuple[EgressProbe, ...],
        browser_runtime_release: str,
        driver: BrowserDriver | None = None,
        lease_for: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if lease_for <= timedelta(0) or len(probes) < 2:
            raise ValueError("Browser Capture requires a positive lease and two probes")
        self._store = store
        self._repository = repository
        self._credentials = credentials
        self._artifacts = artifacts
        self._probes = probes
        self._browser_runtime_release = browser_runtime_release.strip()
        if not self._browser_runtime_release:
            raise ValueError("Browser runtime release is required")
        self._driver = driver or PlaywrightBrowserDriver()
        self._lease_for = lease_for
        self._clock = clock

    def execute(self, lease: WorkerLease) -> Mapping[str, object]:
        preparation = self._repository.prepare(lease)
        self._repository.assert_browser_runtime(
            lease, preparation=preparation,
            observed_release=self._browser_runtime_release, detected_at=self._clock(),
        )
        endpoint = preparation.endpoint
        credential = self._credentials.resolve(
            project_id=lease.project_id,
            reference_id=UUID(str(endpoint["secret_reference_id"])),
            purpose=str(endpoint["secret_purpose"]),
            version=_positive_int(endpoint["secret_version"], maximum=2_147_483_647),
        )
        proxy = build_proxy_lease(endpoint=endpoint, credential=credential, now=self._clock())
        execution = self._repository.start(lease, preparation=preparation, proxy=proxy)
        surface_release, selectors = _surface(preparation.surface)
        profile = _profile(preparation.profile)
        with LeaseHeartbeat(
            self._store,
            lease,
            lease_for=self._lease_for,
            interval=min(self._lease_for / 3, timedelta(seconds=30)),
        ) as heartbeat:
            capture = self._driver.capture(
                query=preparation.question_text,
                expected_surface=surface_release.surface,
                proxy=proxy,
                profile=profile,
                selectors=selectors,
                probes=self._probes,
                now=self._clock(),
            )
            heartbeat.raise_if_stopped()
        parsed = parse_capture(
            release=surface_release,
            egress=capture.verification,
            signals=capture.signals,
        )
        bundle = self._artifacts.persist(
            project_id=lease.project_id,
            attempt_id=preparation.attempt_id,
            capture_session_id=execution.capture_session_id,
            screenshot=capture.screenshot,
            dom=capture.dom,
            har=capture.har,
        )
        observed_at = self._clock()
        with self._store.fenced_transaction(lease) as connection:
            observation_id = self._repository.commit(
                connection,
                lease=lease,
                execution=execution,
                capture=capture,
                parsed=parsed,
                bundle=bundle,
                observed_at=observed_at,
            )
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"workflow-c-observation:{observation_id}",
                details={
                    "observation_id": str(observation_id),
                    "capture_outcome": parsed.outcome.value,
                    "evidence_status": "complete" if parsed.eligible else "ineligible",
                },
            )
        return {
            "status": "succeeded",
            "job_id": str(lease.job_id),
            "observation_id": str(observation_id),
            "capture_outcome": parsed.outcome.value,
            "evidence_status": "complete" if parsed.eligible else "ineligible",
        }


def build_proxy_lease(
    *, endpoint: Mapping[str, object], credential: Mapping[str, object], now: datetime
) -> ProxyLease:
    if now.tzinfo is None or now.utcoffset() is None:
        raise BrowserCaptureError("Proxy lease time must be timezone-aware")
    username = _optional_text(credential.get("username"))
    password = _optional_text(credential.get("password"))
    lease_id = _optional_text(credential.get("lease_id")) or uuid4().hex
    sticky_mode = str(endpoint.get("sticky_mode", ""))
    template = _optional_text(credential.get("username_template"))
    if sticky_mode == "credential_session":
        if template is None or "{session_id}" not in template:
            raise BrowserCaptureError(
                "credential_session proxy Secret requires username_template with {session_id}"
            )
        username = template.replace("{username}", username or "").replace(
            "{session_id}", lease_id
        )
        if "{" in username or "}" in username:
            raise BrowserCaptureError("Proxy username_template contains an unknown placeholder")
    elif sticky_mode == "provider_lease" and "lease_id" not in credential:
        raise BrowserCaptureError("provider_lease proxy Secret requires a provider lease_id")
    connection_reference = _optional_text(credential.get("connection_log_reference"))
    connection_hash = _optional_hash(credential.get("connection_log_hash"))
    if sticky_mode == "trusted_connection_log" and (
        connection_reference is None or connection_hash is None
    ):
        raise BrowserCaptureError(
            "trusted_connection_log proxy Secret requires a trusted log reference and hash"
        )
    if (connection_reference is None) != (connection_hash is None):
        raise BrowserCaptureError("Proxy connection log reference and hash must be paired")
    ttl = _positive_int(credential.get("lease_ttl_seconds", 300), maximum=3600)
    expires_at = now + timedelta(seconds=ttl)
    protocol = str(endpoint.get("protocol", ""))
    host = str(endpoint.get("endpoint_host", "")).strip()
    port = _positive_int(endpoint.get("endpoint_port", 0), maximum=65_535)
    if protocol not in {"http", "https", "socks5"} or not host or not 1 <= port <= 65535:
        raise BrowserCaptureError("Frozen proxy endpoint is invalid")
    return ProxyLease(
        server=f"{protocol}://{host}:{port}",
        username=username,
        password=password,
        lease_id=lease_id,
        started_at=now,
        expires_at=expires_at,
        network_type=NetworkType(str(endpoint["network_type"])),
        expected_region=_optional_text(endpoint.get("expected_region")),
        connection_log_reference=connection_reference,
        connection_log_hash=connection_hash,
    )


def _surface(value: Mapping[str, object]) -> tuple[SurfaceRelease, SurfaceSelectors]:
    selectors = value.get("selectors")
    blocks = value.get("block_detectors")
    hosts = value.get("allowed_hosts")
    if not isinstance(selectors, Mapping) or not isinstance(blocks, Mapping) or not isinstance(hosts, list):
        raise BrowserCaptureError("Frozen Surface Release selectors are invalid")
    required = ("query_input", "page_complete", "surface_marker", "answer", "citations", "page_location")
    parsed_selectors = {name: _required_text(selectors.get(name), f"Surface selector {name}") for name in required}
    return (
        SurfaceRelease(
            id=UUID(str(value["id"])),
            platform=str(value["platform"]),
            surface=str(value["surface"]),
            release_hash=str(value["release_hash"]),
            parser_release=str(value["parser_release"]),
            allowed_hosts=tuple(str(item) for item in hosts),
        ),
        SurfaceSelectors(
            entry_url_template=_required_text(value.get("entry_url_template"), "Surface entry URL"),
            **parsed_selectors,
            block_detectors={str(key): str(item) for key, item in blocks.items()},
            ready_timeout_ms=_positive_int(selectors.get("ready_timeout_ms", 45_000), maximum=180_000),
        ),
    )


def _profile(value: Mapping[str, object]) -> BrowserProfile:
    viewport = value.get("viewport")
    geolocation = value.get("geolocation")
    if not isinstance(viewport, Mapping) or (geolocation is not None and not isinstance(geolocation, Mapping)):
        raise BrowserCaptureError("Frozen Browser Profile is invalid")
    return BrowserProfile(
        locale=str(value["locale"]),
        timezone=str(value["timezone"]),
        viewport_width=_positive_int(viewport.get("width"), maximum=4096),
        viewport_height=_positive_int(viewport.get("height"), maximum=4096),
        user_agent=_optional_text(value.get("user_agent")),
        geolocation=(
            {str(key): float(item) for key, item in geolocation.items()}
            if geolocation is not None
            else None
        ),
        grant_location=bool(value["location_permission"]),
    )


def _required_text(value: object, label: str) -> str:
    result = _optional_text(value)
    if result is None:
        raise BrowserCaptureError(f"{label} is required")
    return result


def _mapping_value(value: object, label: str) -> dict[str, object]:
    candidate = value
    if isinstance(value, str):
        try:
            candidate = json.loads(value)
        except json.JSONDecodeError:
            raise BrowserCaptureError(f"{label} database value is invalid JSON") from None
    if not isinstance(candidate, Mapping) or any(
        not isinstance(key, str) for key in candidate
    ):
        raise BrowserCaptureError(f"{label} database value must be an object")
    return dict(candidate)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 2_000:
        raise BrowserCaptureError("Browser proxy or release text value is invalid")
    return value.strip()


def _optional_hash(value: object) -> str | None:
    result = _optional_text(value)
    if result is not None and (len(result) != 64 or any(c not in "0123456789abcdef" for c in result)):
        raise BrowserCaptureError("Browser proxy connection log hash must be SHA-256")
    return result


def _positive_int(value: object, *, maximum: int) -> int:
    if isinstance(value, bool):
        raise BrowserCaptureError("Browser numeric setting is invalid")
    try:
        result = int(str(value))
    except (TypeError, ValueError):
        raise BrowserCaptureError("Browser numeric setting is invalid") from None
    if not 1 <= result <= maximum:
        raise BrowserCaptureError("Browser numeric setting is outside its supported range")
    return result


__all__ = [
    "BROWSER_CAPTURE_JOB_KIND",
    "BrowserCaptureExecution",
    "BrowserCaptureOperation",
    "BrowserCapturePreparation",
    "BrowserProxyCredentialResolver",
    "PostgresBrowserCaptureWorkerRepository",
    "build_proxy_lease",
]
