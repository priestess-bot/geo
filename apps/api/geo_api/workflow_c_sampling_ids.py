"""Stable command identities shared by Workflow C Sampling adapters."""

from uuid import UUID, uuid5

from geo_core.sampling import SamplingConflict


SAMPLING_API_NAMESPACE = UUID("6cb41f0c-9cc3-58db-a67f-1770bd996c6e")


def sampling_command_id(
    project_id: UUID, operation: str, idempotency_key: str
) -> UUID:
    key = idempotency_key.strip()
    if not key:
        raise SamplingConflict("Idempotency-Key is required")
    return uuid5(SAMPLING_API_NAMESPACE, f"{project_id}:{operation}:{key}")
