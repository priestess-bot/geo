from __future__ import annotations

from datetime import UTC, datetime, timedelta
import base64
import hashlib
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from geo_api.app_factory import create_api_app
from geo_api.synthetic_lab_runtime import SyntheticPageRead
from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.synthetic_lab.domain import SyntheticLabContractError
from geo_core.synthetic_lab.ports import SyntheticLabPermissionDenied
from synthetic_lab_direct_api_test_support import SyntheticLabDirectApiMixin
from synthetic_lab_api_test_support import source_payload as _source_payload


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
TENANT_ID = uuid4()
PROJECT_ID = uuid4()
AUTHORIZATION_ID = uuid4()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _principal(role: str, *, identity_id: UUID | None = None) -> AccessPrincipal:
    return AccessPrincipal(
        identity_id=identity_id or uuid4(),
        actor_id=f"synthetic-{role}",
        tenant_id=TENANT_ID,
        memberships=(MembershipRecord(PROJECT_ID, TENANT_ID, role),),
        auth_method="test",
    )


class PrincipalServices:
    def __init__(self, principal: AccessPrincipal) -> None:
        self.principal = principal

    def authenticate(self, authentication: object) -> AccessPrincipal:
        del authentication
        return self.principal


class MemorySyntheticLabApi(SyntheticLabDirectApiMixin):
    def __init__(self, creator_id: UUID) -> None:
        self.creator_id = creator_id
        self.authorizations = {
            AUTHORIZATION_ID: {
                "id": AUTHORIZATION_ID,
                "project_id": PROJECT_ID,
                "channel": "reddit",
                "adapter_release": "reddit-style-v1",
                "version_number": 1,
                "state": "not_assessed",
                "evidence_reference_hash": None,
                "allowed_purposes": (),
                "max_requests_per_period": None,
                "period_seconds": None,
                "max_concurrency": None,
                "expires_at": None,
                "record_hash": _hash("authorization-v1"),
            }
        }
        self.authorization_submitters = {AUTHORIZATION_ID: creator_id}
        self.sources: dict[UUID, dict[str, Any]] = {}
        self.previews: dict[UUID, dict[str, Any]] = {}
        self.preview_submitters: dict[UUID, UUID] = {}
        self.profiles: dict[UUID, dict[str, Any]] = {}
        self.channel_styles: dict[str, dict[str, Any]] = {}
        self.suites: dict[UUID, dict[str, Any]] = {}
        self.cases: dict[UUID, dict[str, Any]] = {}
        self.jobs: dict[UUID, dict[str, Any]] = {}

    def _check(self, principal: AccessPrincipal, project_id: UUID) -> None:
        if project_id not in principal.project_ids:
            raise SyntheticLabPermissionDenied("Synthetic Lab Project is outside actor scope")

    def _page(self, values: list[object], limit: int, offset: int) -> SyntheticPageRead:
        return SyntheticPageRead(tuple(values[offset : offset + limit]), len(values), limit, offset)

    def list_authorizations(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        return self._page(
            list(self.authorizations.values()), int(values["limit"]), int(values["offset"])
        )

    def create_authorization(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        role = next(
            item.role
            for item in principal.memberships
            if item.project_id == values["project_id"]
        )
        if role not in {"owner", "admin", "operator"}:
            raise SyntheticLabPermissionDenied("authorization creation requires operator role")
        payload = _values(values["payload"])
        authorization_id = uuid4()
        item = {
            "id": authorization_id,
            "project_id": values["project_id"],
            "channel": payload["channel"],
            "adapter_release": payload["adapter_release"],
            "version_number": 1,
            "state": "not_assessed",
            "evidence_reference_hash": None,
            "allowed_purposes": (),
            "max_requests_per_period": None,
            "period_seconds": None,
            "max_concurrency": None,
            "expires_at": None,
            "record_hash": _hash(f"authorization:{authorization_id}:v1"),
            "replayed": False,
        }
        self.authorizations[authorization_id] = item
        self.authorization_submitters[authorization_id] = principal.identity_id
        return dict(item)

    def decide_authorization(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        if principal.identity_id == self.authorization_submitters[values["authorization_id"]]:
            raise SyntheticLabPermissionDenied("submitter cannot approve their own resource")
        payload = _values(values["payload"])
        item = self.authorizations[values["authorization_id"]]
        item.update(
            version_number=payload["expected_version"] + 1,
            state=payload["decision"],
            evidence_reference_hash=(
                _hash(payload["evidence_reference"])
                if payload["evidence_reference"] is not None else None
            ),
            allowed_purposes=tuple(payload["allowed_purposes"]),
            max_requests_per_period=payload["max_requests_per_period"],
            period_seconds=payload["period_seconds"],
            max_concurrency=payload["max_concurrency"],
            expires_at=payload["expires_at"],
            record_hash=_hash(f"authorization-{payload['expected_version'] + 1}"),
            replayed=False,
        )
        return dict(item)

    def revoke_authorization(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        item = self.authorizations[values["authorization_id"]]
        item.update(
            version_number=payload["expected_version"] + 1,
            state="revoked",
            record_hash=_hash(f"authorization-{payload['expected_version'] + 1}"),
            replayed=False,
        )
        return dict(item)

    def reassess_authorization(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        previous = self.authorizations.pop(values["authorization_id"])
        self.authorization_submitters.pop(values["authorization_id"], None)
        reassessment_id = uuid4()
        item = {
            **previous,
            "id": reassessment_id,
            "version_number": payload["expected_version"] + 1,
            "state_version": 1,
            "state": "not_assessed",
            "evidence_reference_hash": None,
            "allowed_purposes": (),
            "max_requests_per_period": None,
            "period_seconds": None,
            "max_concurrency": None,
            "expires_at": None,
            "record_hash": _hash(f"authorization-{payload['expected_version'] + 1}"),
            "replayed": False,
        }
        self.authorizations[reassessment_id] = item
        self.authorization_submitters[reassessment_id] = principal.identity_id
        return dict(item)

    def list_style_sources(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        return self._page(list(self.sources.values()), int(values["limit"]), int(values["offset"]))

    def create_style_source(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        source_id = uuid4()
        locator = payload["source_url"] or payload["source_label"]
        item = {
            "id": source_id,
            "project_id": values["project_id"],
            "source_id": uuid4(),
            "revision_number": payload["expected_version"] + 1,
            "channel": payload["channel"],
            "access_mode": payload["access_mode"],
            "locale": payload["locale"],
            "source_locator_hash": _hash(locator),
            "status": "draft",
            "replayed": False,
        }
        self.sources[source_id] = item
        return item

    def resource_inventory(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        return {
            "samples": [],
            "prompt_bindings": [],
            "question_sets": [],
            "fact_snapshots": [],
            "profiles": [],
            "review_jobs": [],
            "candidate_corpora": [],
            "approved_corpora": [],
        }

    def list_import_previews(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        return self._page(
            list(self.previews.values()), int(values["limit"]), int(values["offset"])
        )

    def create_import_preview(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        content = base64.b64decode(payload["content_base64"], validate=True).decode()
        if "password=" in content.casefold():
            raise SyntheticLabContractError("manual import contains credential material")
        preview_id = uuid4()
        preview = {
            "preview_id": preview_id,
            "project_id": values["project_id"],
            "style_source_revision_id": payload["style_source_revision_id"],
            "channel": "reddit",
            "filename": payload["filename"],
            "import_format": payload["import_format"],
            "submitted_by": principal.identity_id,
            "submitted_at": NOW,
            "expires_at": NOW + timedelta(hours=24),
            "preview_manifest_hash": _hash(f"preview:{preview_id}"),
            "rows": ({
                "row_number": 1,
                "redacted_text": content,
                "source_rights": payload["default_source_rights"],
                "detected_codes": (),
                "blocking_codes": (),
                "disposition": "ready_for_review",
                "selectable": True,
            },),
        }
        record = {
            "preview": preview,
            "status": "pending",
            "version": 1,
            "row_count": 1,
            "selectable_count": 1,
            "blocked_count": 0,
            "replayed": False,
        }
        self.previews[preview_id] = record
        self.preview_submitters[preview_id] = principal.identity_id
        return record

    def get_import_preview(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        return self.previews[values["preview_id"]]

    def approve_import_preview(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        preview_id = values["preview_id"]
        if principal.identity_id == self.preview_submitters[preview_id]:
            raise SyntheticLabPermissionDenied("submitter cannot approve their own import")
        preview = self.previews[preview_id]["preview"]
        self.previews[preview_id].update(status="approved", version=2)
        return {
            "id": uuid4(),
            "project_id": values["project_id"],
            "request_id": uuid4(),
            "channel": preview["channel"],
            "locale": "en-AU",
            "row_count": 1,
            "accepted_count": 1,
            "rejected_count": 0,
            "duplicate_row_count": 0,
            "input_hash": _hash("manual-input"),
            "manifest_hash": _hash("manual-manifest"),
            "row_errors": (),
            "replayed": False,
        }

    def reject_import_preview(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        record = self.previews[values["preview_id"]]
        record.update(status="rejected", version=2)
        return record

    def list_imported_sample_options(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        return self._page([], int(values["limit"]), int(values["offset"]))

    def list_profiles(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        return self._page(list(self.profiles.values()), int(values["limit"]), int(values["offset"]))

    def create_profile(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        version_id = uuid4()
        profile_id = uuid4()
        item = {
            "id": version_id,
            "project_id": values["project_id"],
            "profile_id": profile_id,
            "version_number": payload["expected_version"] + 1,
            "state_version": 1,
            "channel": payload["channel"],
            "locale": payload["locale"],
            "corpus_hash": _hash(f"corpus:{profile_id}"),
            "profile_hash": _hash(f"profile:{profile_id}"),
            "prompt_release_id": payload["prompt_binding_id"],
            "prompt_release_hash": _hash(f"prompt:{payload['prompt_binding_id']}"),
            "approved_sample_count": len(payload["approved_sample_ids"]),
            "status": "draft",
            "replayed": False,
        }
        self.profiles[version_id] = item
        return item

    def submit_profile(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        item = self.profiles[values["profile_version_id"]]
        assert payload["expected_version"] == item["state_version"]
        item.update(status="in_review", state_version=item["state_version"] + 1, replayed=False)
        return item

    def decide_profile(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        item = self.profiles[values["profile_version_id"]]
        assert payload["expected_version"] == item["state_version"]
        item.update(
            status="approved" if payload["decision"] == "approve" else "rejected",
            state_version=item["state_version"] + 1,
            replayed=False,
        )
        return item

    def freeze_profile(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        item = self.profiles[values["profile_version_id"]]
        assert payload["expected_version"] == item["state_version"]
        item.update(status="frozen", state_version=item["state_version"] + 1, replayed=False)
        return item

    def list_suites(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        return self._page(list(self.suites.values()), int(values["limit"]), int(values["offset"]))

    def create_suite(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        version_id = uuid4()
        item = {
            "id": version_id,
            "project_id": values["project_id"],
            "suite_id": uuid4(),
            "version_number": payload["expected_version"] + 1,
            "state_version": 1,
            "channel": payload["channel"],
            "case_count": 0,
            "case_set_hash": _hash(f"case-set:{payload['suite_name']}"),
            "status": "draft",
            "replayed": False,
        }
        self.suites[version_id] = item
        return item

    def freeze_suite(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        item = self.suites[values["suite_version_id"]]
        assert payload["expected_version"] == item["state_version"]
        item.update(status="frozen", state_version=item["state_version"] + 1, replayed=False)
        return item

    def list_cases(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        suite_id = values["suite_version_id"]
        items = [
            item for item in self.cases.values() if item["review_suite_version_id"] == suite_id
        ]
        return self._page(items, int(values["limit"]), int(values["offset"]))

    def create_case(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        case_id = uuid4()
        item = {
            "id": case_id,
            "project_id": values["project_id"],
            "review_suite_version_id": values["suite_version_id"],
            "review_suite_version_number": 1,
            "state_version": 1,
            "case_key": payload["case_key"],
            "ordinal": payload["ordinal"],
            "mode": payload["mode"],
            "channel": payload["channel"],
            "competitor_scenario": payload["competitor_scenario"],
            "content_hash": _hash(f"case-{payload['case_key']}"),
            "replayed": False,
        }
        self.cases[case_id] = item
        return item

    def enqueue_profile_build(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        return self._enqueue_memory_job(
            project_id=values["project_id"],
            kind="style_profile_build",
            seed=f"profile-build:{payload['profile_version_id']}:{payload['runtime_selection_id']}",
        )

    def enqueue_review_case(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        return self._enqueue_memory_job(
            project_id=values["project_id"],
            kind="candidate_generation",
            seed=f"review-case:{payload['suite_version_id']}:{payload['case_id']}",
        )

    def enqueue_corpus_finalize(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        return self._enqueue_memory_job(
            project_id=values["project_id"],
            kind="corpus_finalize",
            seed=f"corpus:{payload['role']}:{payload['review_job_ids']}",
        )

    def enqueue_offline_experiment(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        return self._enqueue_memory_job(
            project_id=values["project_id"],
            kind="offline_experiment",
            seed=f"offline:{payload['question_set_id']}:{payload['candidate_corpus_job_id']}",
        )

    def enqueue_job(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        job = {
            "id": payload["job_id"],
            "project_id": values["project_id"],
            "kind": values["job_kind"],
            "status": "queued",
            "version": 1,
            "input_hash": _hash(f"job-{payload['resource_hash']}"),
            "fencing_token": 0,
            "cancel_requested": False,
            "result_hash": None,
            "replayed": False,
        }
        self.jobs[payload["job_id"]] = job
        return job

    def _enqueue_memory_job(self, *, project_id: UUID, kind: str, seed: str):
        job_id = uuid4()
        job = {
            "id": job_id,
            "project_id": project_id,
            "kind": kind,
            "status": "queued",
            "version": 1,
            "input_hash": _hash(seed),
            "fencing_token": 0,
            "cancel_requested": False,
            "result_hash": None,
            "replayed": False,
        }
        self.jobs[job_id] = job
        return job

    def admit_style_collection(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        job_id = uuid4()
        job = {
            "id": job_id,
            "project_id": values["project_id"],
            "kind": "style_collection",
            "status": "queued",
            "version": 1,
            "input_hash": _hash(f"style-collection:{payload['style_source_revision_id']}"),
            "fencing_token": 0,
            "cancel_requested": False,
            "result_hash": None,
            "replayed": False,
        }
        self.jobs[job_id] = job
        return {
            "disposition": "accepted",
            "reason_code": "live_collection_queued",
            "may_issue_network_request": True,
            "job": job,
        }

    def get_job(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        return self.jobs[values["job_id"]]

    def cancel_job(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        job = self.jobs[values["job_id"]]
        job.update(
            status="cancelled",
            version=payload["expected_version"] + 1,
            cancel_requested=True,
        )
        return job

    def finalize_job(self, principal: AccessPrincipal, **values: object):
        self._check(principal, values["project_id"])
        payload = _values(values["payload"])
        job = self.jobs[values["job_id"]]
        job.update(
            status="succeeded",
            version=payload["expected_version"] + 1,
            fencing_token=payload["fencing_token"],
            result_hash=payload["result_hash"],
        )
        return job


def _values(payload: object) -> dict[str, Any]:
    return payload.model_dump(mode="python")


def _boundary(body: dict[str, Any]) -> None:
    assert body["synthetic"] is True
    assert body["test_only"] is True
    assert body["publication_eligible"] is False


def _app(api: object | None):
    creator = _principal("admin")
    services = PrincipalServices(_principal("admin"))
    app = create_api_app(
        surface="internal",
        services=services,
        synthetic_lab_api=api or object(),
    )
    if api is None:
        app.state.synthetic_lab_api = None
    return app, services, creator


def test_openapi_is_internal_only_strict_redacted_and_stable() -> None:
    internal = create_api_app(surface="internal", synthetic_lab_api=object()).openapi()
    customer = create_api_app(surface="customer", synthetic_lab_api=object()).openapi()
    prefix = "/v1/projects/{project_id}/synthetic-lab"
    expected_paths = {
        f"{prefix}/authorizations",
        f"{prefix}/authorizations/{{authorization_id}}/decision",
        f"{prefix}/authorizations/{{authorization_id}}/revoke",
        f"{prefix}/authorizations/{{authorization_id}}/reassess",
        f"{prefix}/resource-inventory",
        f"{prefix}/style-sources",
        f"{prefix}/sample-import-previews",
        f"{prefix}/sample-import-previews/{{preview_id}}",
        f"{prefix}/sample-import-previews/{{preview_id}}/approve",
        f"{prefix}/sample-import-previews/{{preview_id}}/reject",
        f"{prefix}/sample-options",
        f"{prefix}/style-profiles",
        f"{prefix}/style-profiles/{{profile_version_id}}/submit",
        f"{prefix}/style-profiles/{{profile_version_id}}/decision",
        f"{prefix}/style-profiles/{{profile_version_id}}/freeze",
        f"{prefix}/review-suites",
        f"{prefix}/review-suites/{{suite_version_id}}/cases",
        f"{prefix}/review-suites/{{suite_version_id}}/freeze",
        f"{prefix}/jobs/generation",
        f"{prefix}/jobs/profile-build",
        f"{prefix}/jobs/style-collection",
        f"{prefix}/jobs/revision",
        f"{prefix}/jobs/corpus",
        f"{prefix}/jobs/offline-experiment",
        f"{prefix}/jobs",
        f"{prefix}/jobs/{{job_id}}",
        f"{prefix}/jobs/{{job_id}}/result",
        f"{prefix}/jobs/{{job_id}}/cancel",
        f"{prefix}/jobs/{{job_id}}/finalize",
    }
    assert expected_paths <= set(internal["paths"])
    assert expected_paths.isdisjoint(customer["paths"])
    operations = {
        operation["operationId"]
        for path in expected_paths
        for method, operation in internal["paths"][path].items()
        if method in {"get", "post"}
    }
    assert operations == {
        "createSyntheticCollectionAuthorization",
        "listSyntheticCollectionAuthorizations",
        "decideSyntheticCollectionAuthorization",
        "revokeSyntheticCollectionAuthorization",
        "reassessSyntheticCollectionAuthorization",
        "getSyntheticResourceInventory",
        "listSyntheticStyleSources",
        "createSyntheticStyleSource",
        "listSyntheticManualImportPreviews",
        "createSyntheticManualImportPreview",
        "getSyntheticManualImportPreview",
        "approveSyntheticManualImportPreview",
        "rejectSyntheticManualImportPreview",
        "listSyntheticImportedSampleOptions",
        "listSyntheticStyleProfiles",
        "createSyntheticStyleProfile",
        "submitSyntheticStyleProfile",
        "decideSyntheticStyleProfile",
        "freezeSyntheticStyleProfile",
        "listSyntheticReviewSuites",
        "createSyntheticReviewSuite",
        "listSyntheticReviewCases",
        "createSyntheticReviewCase",
        "freezeSyntheticReviewSuite",
        "enqueueSyntheticGenerationJob",
        "enqueueSyntheticStyleProfileBuildJob",
        "admitSyntheticStyleCollection",
        "enqueueSyntheticRevisionJob",
        "enqueueSyntheticCorpusJob",
        "enqueueSyntheticOfflineExperimentJob",
        "listSyntheticLabJobs",
        "getSyntheticLabJob",
        "getSyntheticLabReviewResult",
        "cancelSyntheticLabJob",
        "finalizeSyntheticLabJob",
    }

    schemas = internal["components"]["schemas"]
    for path in expected_paths:
        for method, operation in internal["paths"][path].items():
            if method not in {"get", "post"}:
                continue
            response_schema = operation["responses"][
                "200"
                if method == "get"
                else next(code for code in ("200", "201", "202") if code in operation["responses"])
            ]["content"]["application/json"]["schema"]
            response = schemas[response_schema["$ref"].rsplit("/", 1)[-1]]
            assert {"synthetic", "test_only", "publication_eligible"} <= set(response["properties"])
            if method == "post":
                key = next(p for p in operation["parameters"] if p["name"] == "Idempotency-Key")
                assert key["required"] is True
                request_ref = operation["requestBody"]["content"]["application/json"]["schema"][
                    "$ref"
                ]
                request_schema = schemas[request_ref.rsplit("/", 1)[-1]]
                if path.endswith("/jobs/style-collection"):
                    assert set(request_schema["required"]) == {
                        "style_source_revision_id",
                        "adapter_release",
                    }
                    assert not {
                        "job_id",
                        "outbox_id",
                        "source_locator_hash",
                        "authorization_hash",
                        "secret_version",
                    }.intersection(request_schema["properties"])
                elif path.endswith("/jobs/profile-build"):
                    assert set(request_schema["required"]) == {
                        "profile_version_id",
                        "fact_snapshot_id",
                        "runtime_selection_id",
                    }
                    assert {
                        "recovery_of_attempt_id",
                        "dify_reconciliation_token",
                    } <= set(request_schema["properties"])
                    assert request_schema["properties"][
                        "dify_reconciliation_token"
                    ]["anyOf"][0]["pattern"] == "^[0-9a-f]{64}$"
                    assert not {"job_id", "outbox_id", "resource_hash"}.intersection(
                        request_schema["properties"]
                    )
                elif path.endswith("/jobs/generation"):
                    assert set(request_schema["required"]) == {
                        "suite_version_id", "case_id", "runtime_selection_id"
                    }
                    assert not {"job_id", "outbox_id", "resource_hash"}.intersection(
                        request_schema["properties"]
                    )
                elif path.endswith("/jobs/corpus"):
                    assert set(request_schema["required"]) == {"role"}
                    assert not {"job_id", "outbox_id", "resource_hash", "runtime_inputs"}.intersection(
                        request_schema["properties"]
                    )
                elif path.endswith("/jobs/offline-experiment"):
                    assert set(request_schema["required"]) == {
                        "question_set_id", "current_corpus_job_id",
                        "candidate_corpus_job_id", "runtime_selection_id"
                    }
                    assert not {"job_id", "outbox_id", "resource_hash", "runtime_inputs"}.intersection(
                        request_schema["properties"]
                    )
                else:
                    assert "expected_version" in request_schema["required"]
                assert request_schema["additionalProperties"] is False

    finalize = schemas["FinalizeSyntheticJobRequest"]
    assert {"lease_id", "fencing_token", "completed_at", "result_hash"} <= set(finalize["required"])
    response_fields = schemas["SyntheticJobResponse"]["properties"]
    assert not {"payload", "lease_id", "model_response", "debug_trace"}.intersection(
        response_fields
    )
    import_request = schemas["CreateManualImportPreviewRequest"]
    assert "content_base64" in import_request["properties"]
    import_fields = schemas["ManualImportPreviewResponse"]["properties"]
    assert not {
        "raw_text",
        "content_base64",
        "cookie_value",
        "authorization_value",
        "password_value",
        "secret_value",
        "storage_state_value",
    }.intersection(import_fields)
    purpose_schema = schemas["DecideAuthorizationRequest"]["properties"]["allowed_purposes"]
    assert purpose_schema["maxItems"] == 1


def test_unavailable_runtime_is_503_and_write_requires_idempotency() -> None:
    app, _, _ = _app(None)
    path = f"/v1/projects/{PROJECT_ID}/synthetic-lab/style-sources"
    payload = _source_payload()
    with TestClient(app) as client:
        missing = client.post(path, json=payload)
        unavailable = client.post(
            path,
            headers={"Idempotency-Key": "synthetic:source:one"},
            json=payload,
        )
    assert missing.status_code == 422
    assert unavailable.status_code == 503
    assert unavailable.headers["Retry-After"] == "30"


def test_initial_authorization_create_is_governed_and_analyst_is_denied() -> None:
    api = MemorySyntheticLabApi(uuid4())
    app, services, _ = _app(api)
    path = f"/v1/projects/{PROJECT_ID}/synthetic-lab/authorizations"
    payload = {
        "expected_version": 0,
        "channel": "reddit",
        "adapter_release": "reddit-style-v2",
    }
    with TestClient(app) as client:
        created = client.post(
            path,
            headers={"Idempotency-Key": "synthetic:authorization:create"},
            json=payload,
        )
        services.principal = _principal("analyst")
        denied = client.post(
            path,
            headers={"Idempotency-Key": "synthetic:authorization:analyst"},
            json={**payload, "adapter_release": "reddit-style-v3"},
        )

    assert created.status_code == 201, created.text
    body = created.json()
    _boundary(body)
    assert body["version_number"] == 1
    assert body["state"] == body["effective_state"] == "not_assessed"
    assert body["evidence_reference_hash"] is None
    assert denied.status_code == 403
