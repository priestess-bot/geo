import pytest

from geo_core.recommendations.postgres import build_recommendation_api
from geo_core.recommendations.postgres.api import PsycopgRecommendationApi


def test_postgres_builder_is_durable_composition_and_does_not_connect_eagerly() -> None:
    api = build_recommendation_api(database_url="postgresql://geo_app:secret@db/geo")

    assert isinstance(api, PsycopgRecommendationApi)


def test_postgres_builder_rejects_an_empty_database_url() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        build_recommendation_api(database_url="  ")
