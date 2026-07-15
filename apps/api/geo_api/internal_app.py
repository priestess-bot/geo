"""ASGI entry point for trusted operators and internal integrations."""

from geo_api.app_factory import create_api_app


app = create_api_app(surface="internal")

