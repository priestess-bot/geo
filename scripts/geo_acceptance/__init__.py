"""Public API for the stable GEO acceptance command."""

from scripts.geo_acceptance.adapters import DeterministicGateway
from scripts.geo_acceptance.contracts import (
    AcceptanceConfig,
    CHANNELS,
    PRODUCT_URL,
)
from scripts.geo_acceptance.runner import run_acceptance

__all__ = [
    "AcceptanceConfig",
    "CHANNELS",
    "DeterministicGateway",
    "PRODUCT_URL",
    "run_acceptance",
]
