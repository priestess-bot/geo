from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest

from geo_core.placements.domain import (
    Destination,
    PackageVersion,
    PlacementRuleViolation,
    WorkflowStatus,
)
from geo_core.placements.publication_contract import (
    parse_frozen_publication_verification_contract,
    parse_publication_verification_contract,
)
from tests.unit.placements.test_placement_workflow import _application


def _manifest(requirements: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema": "geo-prompt-bundle-v3",
        "authoritative": {
            "destination_policy": {
                "disclosure_requirements": dict(requirements),
            }
        },
    }


def _publication_fixture(
    content_json: Mapping[str, object],
    *,
    requirements: Mapping[str, object],
):
    application, repository = _application()
    project_id, campaign_id, opportunity_id, destination_id, bundle_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    version = PackageVersion(
        uuid4(),
        project_id,
        uuid4(),
        bundle_id,
        1,
        content_json,
        "Approved public copy",
        "a" * 64,
        WorkflowStatus.APPROVED,
        campaign_id=campaign_id,
        opportunity_id=opportunity_id,
        destination_id=destination_id,
    )
    repository.packages.append(version)
    repository.bundle_manifests[bundle_id] = _manifest(requirements)
    repository.destinations.append(
        Destination(
            destination_id,
            project_id,
            "owned_site",
            "official-site",
            canonical_url="https://brand.example/",
        )
    )
    return application, repository, version, (project_id, campaign_id, destination_id)


def _request(application, version: PackageVersion, ids: tuple[UUID, UUID, UUID]):
    project_id, campaign_id, destination_id = ids
    return application.request_publication(
        project_id=project_id,
        campaign_id=campaign_id,
        version_id=version.id,
        destination_id=destination_id,
        requested_by=uuid4(),
        publication_attempt=1,
        idempotency_key=f"strict-publication-{uuid4()}",
        restricted_policy_acknowledged=False,
        policy_basis=None,
    )


def test_explicit_arrays_are_preserved_and_nested_decoys_are_ignored() -> None:
    contract = parse_publication_verification_contract(
        {
            "required_disclosures": ["Brand relationship disclosed."],
            "expected_links": ["https://brand.example/product"],
            "metadata": {
                "disclosure": "nested decoy",
                "url": "https://decoy.example/",
            },
        },
        disclosure_required=True,
    )

    assert contract.required_disclosures == ("Brand relationship disclosed.",)
    assert contract.expected_links == ("https://brand.example/product",)


@pytest.mark.parametrize(
    "content_json",
    (
        {"expected_links": []},
        {"required_disclosures": []},
        {"required_disclosures": "disclose", "expected_links": []},
        {"required_disclosures": [], "expected_links": [42]},
    ),
)
def test_missing_or_malformed_contract_rejects_new_publication_without_writes(
    content_json: Mapping[str, object],
) -> None:
    application, repository, version, ids = _publication_fixture(
        content_json, requirements={}
    )

    with pytest.raises(PlacementRuleViolation, match="explicit string array|non-empty strings"):
        _request(application, version, ids)

    assert repository.publications == []


def test_required_destination_disclosure_cannot_be_empty() -> None:
    application, repository, version, ids = _publication_fixture(
        {"required_disclosures": [], "expected_links": []},
        requirements={"commercial_relationship": "required"},
    )

    with pytest.raises(PlacementRuleViolation, match="requires at least one"):
        _request(application, version, ids)

    assert repository.publications == []


def test_explicit_empty_arrays_are_valid_when_frozen_policy_requires_none() -> None:
    application, repository, version, ids = _publication_fixture(
        {"required_disclosures": [], "expected_links": []},
        requirements={"commercial_relationship": False},
    )

    publication = _request(application, version, ids)

    assert repository.publications == [publication]


@pytest.mark.parametrize(
    "manifest",
    (
        {},
        {"schema": "geo-prompt-bundle-v2"},
        {"schema": "geo-prompt-bundle-v3", "authoritative": {}},
    ),
)
def test_legacy_or_malformed_frozen_bundle_is_not_publishable(
    manifest: Mapping[str, object],
) -> None:
    with pytest.raises(PlacementRuleViolation):
        parse_frozen_publication_verification_contract(
            {"required_disclosures": [], "expected_links": []},
            {"manifest": manifest},
        )
