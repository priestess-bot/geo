"""PostgreSQL infrastructure for governed Recommendations."""

from typing import Any

import psycopg
from psycopg.rows import dict_row

from geo_core.model_gateway.postgres_runtime_catalog import PostgresRuntimeCatalog
from geo_core.recommendations.application import RecommendationApplication
from geo_core.recommendations.postgres.api import PsycopgRecommendationApi

from geo_core.recommendations.postgres.evidence import (
    PostgresRecommendationEvidenceResolver,
)
from geo_core.recommendations.postgres.generation_admission import (
    PostgresRecommendationGenerationAdmission,
)
from geo_core.recommendations.postgres.generation_submission import (
    PsycopgRecommendationGenerationSubmission,
)
from geo_core.recommendations.postgres.uow import (
    RecommendationUnitOfWorkFactory,
    block_recommendation_drafts,
)


def build_recommendation_api(*, database_url: str) -> PsycopgRecommendationApi:
    """Build the durable Internal API without a memory or provider fallback."""

    normalized = database_url.strip()
    if not normalized:
        raise ValueError("Recommendation database URL cannot be empty")

    def connect() -> Any:
        return psycopg.connect(normalized, connect_timeout=5, row_factory=dict_row)

    application = RecommendationApplication(
        RecommendationUnitOfWorkFactory(
            connect,
            block_drafts=block_recommendation_drafts,
        )
    )
    generation = PsycopgRecommendationGenerationSubmission(
        connection_factory=connect,
        runtime_catalog=PostgresRuntimeCatalog(normalized),
    )
    return PsycopgRecommendationApi(
        application=application,
        generation=generation,
        connection_factory=connect,
    )


__all__ = [
    "PostgresRecommendationEvidenceResolver",
    "PostgresRecommendationGenerationAdmission",
    "PsycopgRecommendationApi",
    "PsycopgRecommendationGenerationSubmission",
    "build_recommendation_api",
]
