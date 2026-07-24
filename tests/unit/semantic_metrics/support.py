from datetime import UTC, datetime
from uuid import UUID


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
OBSERVATION_IDS = tuple(
    UUID(f"50000000-0000-0000-0000-{index:012d}") for index in range(1, 5)
)
