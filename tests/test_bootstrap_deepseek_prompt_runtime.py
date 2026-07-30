import sys
from uuid import UUID, uuid4

import pytest

from geo_core.access.models import (
    AccessForbidden,
    AccessPrincipal,
    AuthenticationRequired,
    MembershipRecord,
)
from geo_core.secrets import SecretVersionHandle
from geo_core.prompts.test_execution_contracts import PROMPT_TEST_MAXIMUM_PAID_CALLS
import scripts.bootstrap_deepseek_prompt_runtime as bootstrap
from scripts.bootstrap_deepseek_prompt_runtime import (
    ADAPTER_RELEASE_ID,
    DEFAULT_MODEL,
    PROVIDER,
    PROMPT_TEST_RUNTIME_SCOPE,
    SYNTHETIC_REVIEW_ADAPTER_RELEASE_ID,
    SYNTHETIC_REVIEW_PURPOSES,
    SYNTHETIC_REVIEW_RUNTIME_SCOPE,
    _arguments,
    _adapter_release_identity,
    _manifest,
    _project_operator,
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
        bootstrap,
        "PsycopgAccessUnitOfWorkFactory",
        lambda database_url: database_url,
    )
    monkeypatch.setattr(bootstrap, "AccessApplicationService", lambda factory: access)


def test_bootstrap_manifest_is_a_single_purpose_deepseek_prompt_runtime() -> None:
    project_id = uuid4()
    secret = SecretVersionHandle(
        reference_id=uuid4(),
        project_id=project_id,
        purpose="model_provider.deepseek",
        version=1,
    )
    evidence = {
        "capability_reference": "s3://geo-artifacts/runtime/capabilities.json",
        "capability_sha256": "a" * 64,
        "terms_reference": "s3://geo-artifacts/runtime/terms.json",
        "terms_sha256": "b" * 64,
        "approval_reference": "s3://geo-artifacts/runtime/approval.json",
        "approval_sha256": "c" * 64,
    }

    manifest = _manifest(
        project_id=project_id,
        prepared_by=uuid4(),
        approved_by=uuid4(),
        provider_secret=secret,
        configured_model=DEFAULT_MODEL,
        reported_model=DEFAULT_MODEL,
        evidence=evidence,
        purposes=frozenset({"prompt_release_test"}),
        previous_policy_id=None,
        policy_version=1,
        synthetic_review=False,
    )

    runtime = manifest.provider_runtimes[0]
    assert runtime.adapter_release.provider == PROVIDER
    assert runtime.adapter_release.adapter_release_id.startswith(f"{ADAPTER_RELEASE_ID}-")
    assert runtime.allowed_purposes == frozenset({"prompt_release_test"})
    assert runtime.allowed_search_modes == frozenset({"disabled"})
    assert runtime.secret_reference_id == secret.reference_id
    assert manifest.model_releases[0].configured_model == DEFAULT_MODEL
    assert manifest.model_releases[0].model_release_id.endswith(PROMPT_TEST_RUNTIME_SCOPE)
    assert manifest.project_policy.maximum_paid_calls == PROMPT_TEST_MAXIMUM_PAID_CALLS
    assert manifest.project_policy.maximum_concurrent_calls == 1


def test_bootstrap_manifest_can_replace_runtime_for_synthetic_review() -> None:
    project_id = uuid4()
    previous_policy_id = uuid4()
    secret = SecretVersionHandle(
        reference_id=uuid4(),
        project_id=project_id,
        purpose="model_provider.deepseek",
        version=2,
    )
    evidence = {
        "capability_reference": "s3://geo-artifacts/runtime/capabilities.json",
        "capability_sha256": "a" * 64,
        "terms_reference": "s3://geo-artifacts/runtime/terms.json",
        "terms_sha256": "b" * 64,
        "approval_reference": "s3://geo-artifacts/runtime/synthetic-approval.json",
        "approval_sha256": "c" * 64,
    }
    purposes = SYNTHETIC_REVIEW_PURPOSES | {"prompt_release_test"}

    manifest = _manifest(
        project_id=project_id,
        prepared_by=uuid4(),
        approved_by=uuid4(),
        provider_secret=secret,
        configured_model=DEFAULT_MODEL,
        reported_model=DEFAULT_MODEL,
        evidence=evidence,
        purposes=frozenset(purposes),
        previous_policy_id=previous_policy_id,
        policy_version=2,
        synthetic_review=True,
    )

    runtime = manifest.provider_runtimes[0]
    assert runtime.adapter_release.adapter_release_id.startswith(
        f"{SYNTHETIC_REVIEW_ADAPTER_RELEASE_ID}-"
    )
    assert runtime.allowed_purposes == purposes
    assert "recommendations.recommendation" in runtime.allowed_purposes
    assert runtime.allowed_search_modes == frozenset({"disabled", None})
    assert manifest.model_releases[0].model_release_id.endswith(
        SYNTHETIC_REVIEW_RUNTIME_SCOPE
    )
    assert manifest.policy_version == 2
    assert manifest.previous_policy_version_id == previous_policy_id


def test_adapter_release_identity_changes_with_project_scoped_evidence() -> None:
    first = {
        "capability_reference": "s3://geo-artifacts/project-a/capabilities.json",
        "capability_sha256": "a" * 64,
        "terms_reference": "s3://geo-artifacts/project-a/terms.json",
        "terms_sha256": "b" * 64,
    }
    second = {**first, "capability_reference": first["capability_reference"].replace("a/", "b/")}

    assert _adapter_release_identity(ADAPTER_RELEASE_ID, first) == _adapter_release_identity(
        ADAPTER_RELEASE_ID, first
    )
    assert _adapter_release_identity(ADAPTER_RELEASE_ID, first) != _adapter_release_identity(
        ADAPTER_RELEASE_ID, second
    )


def test_bootstrap_manifest_freezes_observed_model_behind_configured_alias() -> None:
    project_id = uuid4()
    secret = SecretVersionHandle(
        reference_id=uuid4(),
        project_id=project_id,
        purpose="model_provider.deepseek",
        version=1,
    )
    evidence = {
        "capability_reference": "s3://geo-artifacts/runtime/capabilities.json",
        "capability_sha256": "a" * 64,
        "terms_reference": "s3://geo-artifacts/runtime/terms.json",
        "terms_sha256": "b" * 64,
        "approval_reference": "s3://geo-artifacts/runtime/approval.json",
        "approval_sha256": "c" * 64,
    }

    manifest = _manifest(
        project_id=project_id,
        prepared_by=uuid4(),
        approved_by=uuid4(),
        provider_secret=secret,
        configured_model="deepseek-chat",
        reported_model="deepseek-v4-flash",
        evidence=evidence,
        purposes=frozenset(SYNTHETIC_REVIEW_PURPOSES | {"prompt_release_test"}),
        previous_policy_id=uuid4(),
        policy_version=3,
        synthetic_review=True,
    )

    release = manifest.model_releases[0]
    assert release.configured_model == "deepseek-chat"
    assert release.reported_model_policy.value == "allowlist"
    assert release.allowed_reported_models == ("deepseek-v4-flash",)


def test_bootstrap_operator_uses_the_stored_owner_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity_id = uuid4()
    tenant_id = uuid4()
    project_id = uuid4()
    principal = AccessPrincipal(
        identity_id=identity_id,
        actor_id="oidc-owner-subject",
        tenant_id=tenant_id,
        memberships=(MembershipRecord(project_id, tenant_id, "owner"),),
        auth_method="development",
    )
    _stub_access(monkeypatch, _AccessStub(principal))

    operator = _project_operator(
        database_url="postgresql://redacted",
        identity_id=identity_id,
        project_id=project_id,
        tenant_id=tenant_id,
        auth_method="operator-bootstrap-preparation",
        label="--prepared-by",
    )

    assert operator.actor_id == "oidc-owner-subject"
    assert operator.roles == ("owner",)
    assert operator.auth_method == "operator-bootstrap-preparation"


@pytest.mark.parametrize(
    "case",
    ["unknown_identity", "analyst", "wrong_project", "wrong_tenant", "revoked"],
)
def test_bootstrap_operator_rejects_unknown_or_non_manager_identity(
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
        SystemExit,
        match="--approved-by must reference an active owner/admin membership",
    ):
        _project_operator(
            database_url="postgresql://must-not-appear",
            identity_id=identity_id,
            project_id=project_id,
            tenant_id=tenant_id,
            auth_method="operator-bootstrap-approval",
            label="--approved-by",
        )


def test_bootstrap_requires_an_explicit_human_preparer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bootstrap_deepseek_prompt_runtime.py",
            "--project-id",
            str(uuid4()),
            "--tenant-id",
            str(uuid4()),
            "--approved-by",
            str(uuid4()),
        ],
    )
    monkeypatch.setenv("GEO_MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ID", str(uuid4()))

    with pytest.raises(SystemExit) as exc_info:
        _arguments()

    assert exc_info.value.code == 2
