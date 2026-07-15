"""Top-level orchestration for the stable GEO acceptance lifecycle."""

from __future__ import annotations

from scripts.geo_acceptance.contracts import AcceptanceConfig
from scripts.geo_acceptance.monitoring import run_baseline
from scripts.geo_acceptance.placement import run_placement
from scripts.geo_acceptance.reporting import build_result, run_reporting, write_result
from scripts.geo_acceptance.setup import setup_acceptance


def run_acceptance(config: AcceptanceConfig) -> dict[str, object]:
    """Run the complete controlled lifecycle and return its immutable ID manifest."""

    config.validate()
    setup = setup_acceptance(config)
    baseline = run_baseline(setup, app_database_url=config.app_database_url.strip())
    placement = run_placement(config, setup, baseline)
    reporting = run_reporting(setup, baseline, placement)
    result = build_result(config, setup, baseline, placement, reporting)
    write_result(config.output_path, result)
    return result
