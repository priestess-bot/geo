from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from geo_core.access.models import (
    AccessForbidden,
    AccessPrincipal,
    AuthenticationRequired,
    MembershipRecord,
)
from geo_core.workflow_runtime import DIFY_WORKFLOW_PURPOSES, PublishedWorkflowSnapshot
import scripts.enroll_dify_workflows as enrollment
from scripts.enroll_dify_workflows import (
    EnrollmentError,
    _manifest_rows,
    _project_operator,
    _verified_published_snapshot,
    enroll_workflows,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "infra" / "dify" / "workflows" / "manifest.json"


class _PublishedReader:
    def __init__(self, snapshot: PublishedWorkflowSnapshot) -> None:
        self.snapshot = snapshot

    def read(self, *, purpose: str, app_id: str) -> PublishedWorkflowSnapshot:
        assert purpose == self.snapshot.purpose
        assert app_id == self.snapshot.app_id
        return self.snapshot


def _published_snapshot() -> PublishedWorkflowSnapshot:
    timestamp = datetime(2026, 7, 28, tzinfo=UTC)
    return PublishedWorkflowSnapshot(
        purpose="synthetic_lab.style_profile",
        app_id="style-app",
        workflow_id="style-workflow",
        workflow_hash="a" * 64,
        snapshot_hash="b" * 64,
        prompt_nodes=({"node_id": "llm", "model_name": "deepseek-chat"},),
        input_variables=({"name": "geo_context_json"},),
        graph_nodes=({"node_id": "llm", "type": "llm"},),
        published_at=timestamp,
        observed_at=timestamp,
    )


class _AccessStub:
    def __init__(self, principal: AccessPrincipal | None) -> None:
        self.principal = principal

    def authenticate_development(self, *, identity_id: UUID, tenant_id: UUID) -> AccessPrincipal:
        if self.principal is None or self.principal.identity_id != identity_id:
            raise AuthenticationRequired("invalid")
        if self.principal.tenant_id != tenant_id:
            raise AccessForbidden("wrong tenant")
        return self.principal

    def require_project_role(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        allowed_roles: frozenset[str],
    ) -> str:
        membership = next(
            (item for item in principal.memberships if item.project_id == project_id),
            None,
        )
        if membership is None or membership.role not in allowed_roles:
            raise AccessForbidden("forbidden")
        return membership.role


def _stub_access(monkeypatch: pytest.MonkeyPatch, access: _AccessStub) -> None:
    monkeypatch.setattr(
        enrollment,
        "PsycopgAccessUnitOfWorkFactory",
        lambda database_url: database_url,
    )
    monkeypatch.setattr(enrollment, "AccessApplicationService", lambda factory: access)


def test_enrollment_manifest_exactly_covers_all_ten_dify_workflows() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    rows = _manifest_rows(manifest)

    assert len(rows) == 10
    assert {row["purpose"] for row in rows} == DIFY_WORKFLOW_PURPOSES


def test_enrollment_registers_only_the_graph_read_from_the_dify_console() -> None:
    snapshot = _published_snapshot()

    observed = _verified_published_snapshot(
        published_reader=_PublishedReader(snapshot),  # type: ignore[arg-type]
        purpose=snapshot.purpose,
        item={
            "app_id": snapshot.app_id,
            "workflow_id": snapshot.workflow_id,
            "workflow_hash": snapshot.workflow_hash,
        },
    )

    assert observed.snapshot_hash == "b" * 64


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("workflow_id", "tampered-workflow", "Workflow ID differs"),
        ("workflow_hash", "c" * 64, "Workflow hash differs"),
    ],
)
def test_enrollment_rejects_private_state_that_differs_from_the_console(
    field: str,
    value: str,
    message: str,
) -> None:
    snapshot = _published_snapshot()
    item = {
        "app_id": snapshot.app_id,
        "workflow_id": snapshot.workflow_id,
        "workflow_hash": snapshot.workflow_hash,
    }
    item[field] = value

    with pytest.raises(EnrollmentError, match=message):
        _verified_published_snapshot(
            published_reader=_PublishedReader(snapshot),  # type: ignore[arg-type]
            purpose=snapshot.purpose,
            item=item,
        )


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_enrollment_rejects_an_incomplete_or_duplicate_workflow_catalog(
    mutation: str,
) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    workflows = manifest["workflows"]
    assert isinstance(workflows, list)
    if mutation == "missing":
        workflows.pop()
    else:
        workflows[-1] = dict(workflows[0])

    with pytest.raises(
        EnrollmentError,
        match="must contain every supported purpose exactly once",
    ):
        _manifest_rows(manifest)


def test_enrollment_operator_uses_the_stored_admin_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity_id = uuid4()
    tenant_id = uuid4()
    project_id = uuid4()
    principal = AccessPrincipal(
        identity_id=identity_id,
        actor_id="oidc-admin-subject",
        tenant_id=tenant_id,
        memberships=(MembershipRecord(project_id, tenant_id, "admin"),),
        auth_method="development",
    )
    _stub_access(monkeypatch, _AccessStub(principal))

    operator = _project_operator(
        database_url="postgresql://redacted",
        identity_id=identity_id,
        project_id=project_id,
        tenant_id=tenant_id,
        auth_method="dify-enrollment-approver",
        label="approver",
    )

    assert operator.actor_id == "oidc-admin-subject"
    assert operator.roles == ("admin",)
    assert operator.auth_method == "dify-enrollment-approver"


@pytest.mark.parametrize(
    "case",
    ["unknown_identity", "analyst", "wrong_project", "wrong_tenant", "revoked"],
)
def test_enrollment_operator_rejects_unknown_or_non_manager_identity(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    identity_id = uuid4()
    tenant_id = uuid4()
    project_id = uuid4()
    membership_project_id = uuid4() if case == "wrong_project" else project_id
    membership_tenant_id = uuid4() if case == "wrong_tenant" else tenant_id
    role = "analyst" if case == "analyst" else "admin"
    memberships = (
        ()
        if case == "revoked"
        else (MembershipRecord(membership_project_id, membership_tenant_id, role),)
    )
    principal = (
        None
        if case == "unknown_identity"
        else (
            AccessPrincipal(
                identity_id=identity_id,
                actor_id="oidc-analyst-subject",
                tenant_id=membership_tenant_id,
                memberships=memberships,
                auth_method="development",
            )
        )
    )
    _stub_access(monkeypatch, _AccessStub(principal))

    with pytest.raises(
        EnrollmentError,
        match="preparer must reference an active owner/admin membership",
    ):
        _project_operator(
            database_url="postgresql://must-not-appear",
            identity_id=identity_id,
            project_id=project_id,
            tenant_id=tenant_id,
            auth_method="dify-enrollment-preparer",
            label="preparer",
        )


def test_enrollment_function_rejects_the_same_preparer_and_approver_before_io(
    tmp_path: Path,
) -> None:
    identity_id = uuid4()

    with pytest.raises(EnrollmentError, match="must be distinct identities"):
        enroll_workflows(
            database_url="postgresql://unused",
            project_id=uuid4(),
            tenant_id=uuid4(),
            preparer_id=identity_id,
            approver_id=identity_id,
            state={},
            state_file=tmp_path / "state.json",
            manifest={},
            manifest_dir=tmp_path,
            master_keyring_file=tmp_path / "keyring.json",
            request_hash_key_file=tmp_path / "request-hash-key",
        )
