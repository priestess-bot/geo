"""Lease-owned Style Collection orchestration with fail-closed navigation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
import hashlib
from urllib.parse import urlsplit

from geo_core.jobs.postgres import (
    JobCancellationRequested,
    LeaseHeartbeat,
    LostJobLease,
    PostgresDurableJobStore,
    WorkerLease,
)
from geo_core.synthetic_lab.authorization import recheck_before_navigation
from geo_core.synthetic_lab.collection_execution_contracts import (
    CollectionBlockReason,
    CollectionOutcome,
    StyleArtifactInspectorPort,
    StyleCollectionExecutionError,
    StyleCollectionOutput,
    StyleCollectionRepositoryPort,
    StyleCollectionSecretResolverPort,
    StyleCollectionTask,
    StyleCollectorPort,
    StylePageCapture,
    StyleTextExtractorPort,
)
from geo_core.synthetic_lab.domain import SyntheticLabContractError
from geo_core.synthetic_lab.ports import CollectionAuthorizationPort
from geo_core.synthetic_lab.raw_artifact_governance import RawArtifactInspection
from geo_core.synthetic_lab.raw_artifact_storage import GovernedRawArtifactStorage
from geo_core.synthetic_lab.raw_artifact_storage_contracts import RawArtifactWriteRequest


class _CollectionStopped(StyleCollectionExecutionError):
    def __init__(self, reason: CollectionBlockReason, attempted_url: str) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.attempted_url_hash = hashlib.sha256(attempted_url.encode()).hexdigest()


class StyleCollectionHandler:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        repository: StyleCollectionRepositoryPort,
        authorizations: CollectionAuthorizationPort,
        collector: StyleCollectorPort,
        secrets: StyleCollectionSecretResolverPort,
        extractor: StyleTextExtractorPort,
        inspector: StyleArtifactInspectorPort,
        artifacts: GovernedRawArtifactStorage,
        lease_for: timedelta,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if lease_for.total_seconds() < 3:
            raise ValueError("Style Collection lease must be at least three seconds")
        self._store = store
        self._repository = repository
        self._authorizations = authorizations
        self._collector = collector
        self._secrets = secrets
        self._extractor = extractor
        self._inspector = inspector
        self._artifacts = artifacts
        self._lease_for = lease_for
        self._clock = clock or (lambda: datetime.now(UTC))

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        capture: StylePageCapture | None = None
        temporary_payloads: list[bytearray] = []
        try:
            task = self._repository.load(lease)
            _assert_task_matches_lease(task, lease)
            with LeaseHeartbeat(
                self._store,
                lease,
                lease_for=self._lease_for,
                interval=min(self._lease_for / 3, timedelta(seconds=30)),
            ) as heartbeat:
                self._checkpoint(lease, task, heartbeat)
                credential = (
                    self._secrets.resolve(task.login_secret)
                    if task.login_secret is not None
                    else None
                )
                guarded_urls: list[str] = []

                def guard(url: str) -> None:
                    self._checkpoint(lease, task, heartbeat)
                    _assert_navigation_allowed(task, url, guarded_urls)
                    robots = self._collector.check_robots(task, url)
                    self._checkpoint(lease, task, heartbeat)
                    if not robots.allowed:
                        raise _CollectionStopped(CollectionBlockReason.ROBOTS_DENIED, url)
                    guarded_urls.append(url)

                capture = self._collector.collect(
                    task,
                    credential=credential,
                    before_navigation=guard,
                )
                del credential
                self._checkpoint(lease, task, heartbeat)
                if tuple(guarded_urls) != capture.navigation_chain:
                    raise StyleCollectionExecutionError(
                        "collector navigation did not pass the complete guard chain"
                    )
            if capture.raw_bundle is not None:
                temporary_payloads.append(capture.raw_bundle)
            if capture.block_reason is not None:
                output = _blocked_output(task, capture)
            else:
                output, values = self._persist_capture(lease, task, capture)
                temporary_payloads.extend(values)
            self._finalize(lease, task, output)
            return {
                "status": "succeeded",
                "job_id": str(lease.job_id),
                "outcome": output.outcome.value,
                "result_hash": output.result_hash,
            }
        except _CollectionStopped as error:
            task = self._repository.load(lease)
            output = StyleCollectionOutput(
                project_id=task.project_id,
                collection_run_id=task.collection_run_id,
                outcome=CollectionOutcome.ACCESS_BLOCKED,
                final_url_hash=error.attempted_url_hash,
                navigation_chain_hash=hashlib.sha256(b"blocked-before-navigation").hexdigest(),
                raw_manifest_hash=None,
                derived_manifest_hash=None,
                derived_content_hash=None,
                extracted_record_count=0,
                block_reason=error.reason,
            )
            try:
                self._finalize(lease, task, output)
            except (JobCancellationRequested, LostJobLease):
                self._orphan_attempt(lease, "blocked_finalize_lease_lost")
                raise
            return {
                "status": "succeeded",
                "job_id": str(lease.job_id),
                "outcome": output.outcome.value,
                "result_hash": output.result_hash,
            }
        except (JobCancellationRequested, LostJobLease):
            self._orphan_attempt(lease, "lease_lost_or_cancelled")
            raise
        except (StyleCollectionExecutionError, SyntheticLabContractError):
            self._orphan_attempt(lease, "collection_contract_failure")
            return self._fail(lease, retry=False, classification="contract")
        except Exception as error:
            self._orphan_attempt(lease, "collection_retryable_failure")
            return self._fail(
                lease,
                retry=True,
                classification=type(error).__name__,
            )
        finally:
            if capture is not None and capture.raw_bundle is not None:
                temporary_payloads.append(capture.raw_bundle)
            for payload in temporary_payloads:
                _wipe(payload)

    def _checkpoint(
        self,
        lease: WorkerLease,
        task: StyleCollectionTask,
        heartbeat: LeaseHeartbeat,
    ) -> None:
        heartbeat.raise_if_stopped()
        self._store.heartbeat(lease, lease_for=self._lease_for)
        current = self._authorizations.current(task.authorization)
        navigation = recheck_before_navigation(
            task.authorization,
            current,
            at=self._clock(),
        )
        if not navigation.proceed:
            raise _CollectionStopped(CollectionBlockReason.AUTHORIZATION_STALE, task.source_url)
        heartbeat.raise_if_stopped()

    def _persist_capture(
        self,
        lease: WorkerLease,
        task: StyleCollectionTask,
        capture: StylePageCapture,
    ) -> tuple[StyleCollectionOutput, list[bytearray]]:
        raw = self._inspector.inspect_raw(task, capture)
        extracted = self._extractor.extract(task, capture)
        derived = self._inspector.inspect_derived(task, capture, extracted)
        raw_result = self._artifacts.persist(
            _artifact_request(
                lease,
                task,
                raw.inspection,
                raw.payload,
                media_type=capture.raw_media_type,
                record_count=1,
                producer_release=capture.capture_release,
            )
        )
        derived_result = self._artifacts.persist(
            _artifact_request(
                lease,
                task,
                derived.inspection,
                derived.payload,
                media_type="text/plain; charset=utf-8",
                record_count=extracted.record_count,
                producer_release=extracted.parser_release,
            )
        )
        if derived_result.persisted is None:
            raise StyleCollectionExecutionError("derived Style Collection artifact was rejected")
        raw_manifest = (
            raw_result.persisted.manifest.manifest_hash
            if raw_result.persisted is not None
            else None
        )
        output = StyleCollectionOutput(
            project_id=task.project_id,
            collection_run_id=task.collection_run_id,
            outcome=CollectionOutcome.CAPTURED,
            final_url_hash=hashlib.sha256(capture.final_url.encode()).hexdigest(),
            navigation_chain_hash=canonical_url_chain_hash(capture.navigation_chain),
            raw_manifest_hash=raw_manifest,
            derived_manifest_hash=derived_result.persisted.manifest.manifest_hash,
            derived_content_hash=derived_result.decision.persisted_content_hash,
            extracted_record_count=extracted.record_count,
            block_reason=None,
        )
        return output, [raw.payload, extracted.payload, derived.payload]

    def _finalize(
        self,
        lease: WorkerLease,
        task: StyleCollectionTask,
        output: StyleCollectionOutput,
    ) -> None:
        with self._store.fenced_transaction(lease) as connection:
            self._repository.finalize(
                connection=connection,
                lease=lease,
                task=task,
                output=output,
            )
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"synthetic://style-collection/{output.result_hash}",
                details={
                    "outcome": output.outcome.value,
                    "result_hash": output.result_hash,
                    "task_input_hash": task.input_hash,
                },
            )

    def _fail(
        self,
        lease: WorkerLease,
        *,
        retry: bool,
        classification: str,
    ) -> Mapping[str, object]:
        self._store.heartbeat(lease, lease_for=self._lease_for)
        status = self._store.fail(
            lease,
            error_code="style_collection_execution",
            details={"classification": classification},
            retry_delay=timedelta(seconds=30) if retry else None,
        )
        return {"status": status, "job_id": str(lease.job_id)}

    def _orphan_attempt(self, lease: WorkerLease, reason: str) -> None:
        self._repository.mark_attempt_orphaned(lease=lease, reason=reason)


def _artifact_request(
    lease: WorkerLease,
    task: StyleCollectionTask,
    inspection: RawArtifactInspection,
    payload: bytearray,
    *,
    media_type: str,
    record_count: int,
    producer_release: str,
) -> RawArtifactWriteRequest:
    return RawArtifactWriteRequest(
        lease=lease,
        inspection=inspection,
        payload=payload,
        media_type=media_type,
        source_identity_hash=task.source_locator_hash,
        record_count=record_count,
        producer_release=producer_release,
    )


def _blocked_output(task: StyleCollectionTask, capture: StylePageCapture) -> StyleCollectionOutput:
    return StyleCollectionOutput(
        project_id=task.project_id,
        collection_run_id=task.collection_run_id,
        outcome=CollectionOutcome.ACCESS_BLOCKED,
        final_url_hash=hashlib.sha256(capture.final_url.encode()).hexdigest(),
        navigation_chain_hash=canonical_url_chain_hash(capture.navigation_chain),
        raw_manifest_hash=None,
        derived_manifest_hash=None,
        derived_content_hash=None,
        extracted_record_count=0,
        block_reason=capture.block_reason,
    )


def _assert_task_matches_lease(task: StyleCollectionTask, lease: WorkerLease) -> None:
    if task.project_id != lease.project_id or task.job_id != lease.job_id:
        raise StyleCollectionExecutionError("collection task does not match claimed Job")
    if lease.kind not in {"style.collect", "style_collection"}:
        raise StyleCollectionExecutionError("claimed Job kind is not Style Collection")
    if task.login_secret is not None and task.login_secret.purpose != (
        f"style_collection_login.{task.channel}"
    ):
        raise StyleCollectionExecutionError("collection login Secret purpose changed")


def _assert_navigation_allowed(
    task: StyleCollectionTask,
    url: str,
    guarded_urls: list[str],
) -> None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or host not in task.allowed_redirect_hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise _CollectionStopped(CollectionBlockReason.REDIRECT_DENIED, url)
    if len(guarded_urls) > task.maximum_redirects:
        raise _CollectionStopped(CollectionBlockReason.REDIRECT_DENIED, url)


def canonical_url_chain_hash(values: tuple[str, ...]) -> str:
    encoded = "\n".join(values).encode()
    return hashlib.sha256(encoded).hexdigest()


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


__all__ = ["StyleCollectionHandler", "canonical_url_chain_hash"]
