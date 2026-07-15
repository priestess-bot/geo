"""ASGI entry point for trusted operators and internal integrations."""

from geo_api.app_factory import create_api_app
from geo_api.placement_bootstrap import placement_application_from_environment


app = create_api_app(
    surface="internal",
    placement_services=placement_application_from_environment(),
)
