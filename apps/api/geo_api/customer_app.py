"""ASGI entry point exposing customer-safe projections only."""

from geo_api.app_factory import create_api_app


app = create_api_app(surface="customer")

