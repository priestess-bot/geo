"""Small immutable records shared by placement worker adapters."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class VerificationSnapshot:
    submission_id: UUID
    publication_request_id: UUID
    submitted_url: str
    expected_text_fragments: tuple[str, ...]
    required_disclosures: tuple[str, ...]
    expected_links: tuple[str, ...]
    allowed_hosts: tuple[str, ...]


@dataclass(frozen=True)
class ModelCallReservation:
    call_number: int
    request_hash: str
    provider: str
