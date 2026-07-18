"""Top-level orchestration for the stable GEO acceptance lifecycle."""

from __future__ import annotations

import json

from scripts.geo_acceptance.contracts import AcceptanceConfig
from scripts.geo_acceptance.isolation import InlineIsolationGuard
from scripts.geo_acceptance.monitoring import run_baseline
from scripts.geo_acceptance.placement import run_placement
from scripts.geo_acceptance.reporting import build_result, run_reporting, write_result
from scripts.geo_acceptance.setup import setup_acceptance


def run_acceptance(config: AcceptanceConfig) -> dict[str, object]:
    """Run the complete controlled lifecycle and return its immutable ID manifest."""

    config.validate()
    config.validate_inline_isolation()
    with InlineIsolationGuard.acquire(config) as isolation:
        setup = setup_acceptance(config)
        isolation.assert_created_scope(
            tenant_id=setup.bootstrap.tenant_id, project_id=setup.project_id
        )
        if config.customer_invitation_output is not None:
            config.customer_invitation_output.parent.mkdir(parents=True, exist_ok=True)
            config.customer_invitation_output.write_text(
                json.dumps(
                    {
                        "invitation": {"id": str(setup.customer_invitation_id)},
                        "invite_token": setup.customer_invite_token,
                        "classification": "staging-secret-delete-after-browser-capture",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            config.customer_invitation_output.chmod(0o600)
        baseline = run_baseline(setup, app_database_url=config.app_database_url.strip())
        placement = run_placement(config, setup, baseline)
        reporting = run_reporting(setup, baseline, placement)
        result = build_result(
            config,
            setup,
            baseline,
            placement,
            reporting,
            isolation_evidence=isolation.evidence,
        )
        write_result(config.output_path, result)
        return result
