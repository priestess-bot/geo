from uuid import uuid4

from geo_core.secrets import SecretVersionHandle
from scripts.bootstrap_deepseek_prompt_runtime import (
    ADAPTER_RELEASE_ID,
    DEFAULT_MODEL,
    PROVIDER,
    _manifest,
)


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
        evidence=evidence,
    )

    runtime = manifest.provider_runtimes[0]
    assert runtime.adapter_release.provider == PROVIDER
    assert runtime.adapter_release.adapter_release_id == ADAPTER_RELEASE_ID
    assert runtime.allowed_purposes == frozenset({"prompt_release_test"})
    assert runtime.allowed_search_modes == frozenset({"disabled"})
    assert runtime.secret_reference_id == secret.reference_id
    assert manifest.model_releases[0].configured_model == DEFAULT_MODEL
    assert manifest.project_policy.maximum_paid_calls == 5
    assert manifest.project_policy.maximum_concurrent_calls == 1
