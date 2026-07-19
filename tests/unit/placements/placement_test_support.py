from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from geo_core.placements.domain import (
    Destination,
    JobReference,
    Measurement,
    PackageVersion,
    PlacementConflict,
    PlacementRuleViolation,
    PublicationRequest,
    Submission,
    WorkflowStatus,
)


OUTPUT_SCHEMA = {
    "type": "object",
    "required": [
        "content_json",
        "rendered_text",
        "claims",
        "internal_evidence_refs",
        "public_citation_refs",
    ],
    "properties": {
        "content_json": {
            "type": "object",
            "required": ["required_disclosures", "expected_links"],
            "properties": {
                "required_disclosures": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "expected_links": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["text", "kind", "support_status", "evidence_item_ids"],
            },
        }
    },
}


class PublicationRepositorySupport:
    destinations: list[Destination]

    def __init__(self) -> None:
        self.bundle_manifests: dict[UUID, dict[str, object]] = {}
        self.publications: list[PublicationRequest] = []
        self.submissions: list[Submission] = []
        self.submission_hashes: dict[str, str] = {}
        self.measurements: list[Measurement] = []

    def get_package_version(self, **values: Any) -> PackageVersion:
        raise NotImplementedError

    def _job(
        self, project_id: UUID, campaign_id: UUID | None, kind: str
    ) -> JobReference:
        raise NotImplementedError

    def get_prompt_bundle(
        self, *, project_id: UUID, bundle_id: UUID
    ) -> dict[str, object] | None:
        manifest = self.bundle_manifests.get(bundle_id)
        if manifest is None:
            return None
        return {"id": bundle_id, "project_id": project_id, "manifest": manifest}

    def create_publication_request(self, **values: Any) -> PublicationRequest:
        version = self.get_package_version(
            project_id=values["project_id"], version_id=values["version_id"]
        )
        if version.workflow_status != WorkflowStatus.APPROVED:
            raise PlacementRuleViolation("publication requires approved version")
        destination = next(
            item for item in self.destinations if item.id == values["destination_id"]
        )
        item = PublicationRequest(
            id=uuid4(),
            project_id=values["project_id"],
            package_version_id=version.id,
            destination_id=destination.id,
            publication_channel=destination.publication_channel,
            destination_key=destination.destination_key,
            publication_attempt=values["publication_attempt"],
            idempotency_key=values["idempotency_key"],
            restricted_policy_acknowledged=values["restricted_policy_acknowledged"],
            policy_basis=values["policy_basis"],
            campaign_id=version.campaign_id,
            opportunity_id=version.opportunity_id,
        )
        self.publications.append(item)
        return item

    def create_submission(self, **values: Any) -> Submission:
        replay = next(
            (
                item
                for item in self.submissions
                if item.idempotency_key == values["idempotency_key"]
            ),
            None,
        )
        if replay is not None:
            if self.submission_hashes[values["idempotency_key"]] != values["payload_hash"]:
                raise PlacementConflict("idempotency key reused with different payload")
            return replay
        publication = next(
            item
            for item in self.publications
            if item.id == values["publication_request_id"]
        )
        item = Submission(
            uuid4(),
            values["project_id"],
            values["publication_request_id"],
            "submitted" if values["submitted_url"] else "awaiting_url",
            values["idempotency_key"],
            values["submitted_by"],
            values["submitted_url"],
            values["provider_submission_id"],
            campaign_id=publication.campaign_id,
            opportunity_id=publication.opportunity_id,
            destination_id=publication.destination_id,
        )
        self.submissions.append(item)
        self.submission_hashes[values["idempotency_key"]] = values["payload_hash"]
        return item

    def enqueue_verification(self, **values: Any) -> JobReference:
        submission = next(
            item for item in self.submissions if item.id == values["submission_id"]
        )
        return self._job(
            values["project_id"], submission.campaign_id, "publication.verify"
        )

    def record_measurement(self, **values: Any) -> Measurement:
        submission = next(
            item for item in self.submissions if item.id == values["submission_id"]
        )
        item = Measurement(
            id=uuid4(),
            **values,
            campaign_id=submission.campaign_id,
            opportunity_id=submission.opportunity_id,
            destination_id=submission.destination_id,
        )
        self.measurements.append(item)
        return item

    def list_measurements(self, **values: Any) -> tuple[Measurement, ...]:
        return tuple(
            item
            for item in self.measurements
            if item.submission_id == values["submission_id"]
        )
