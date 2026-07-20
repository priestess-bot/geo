#!/usr/bin/env python3
"""Fail closed when an inline acceptance report overstates what it proved."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping


def verify_report(payload: object) -> None:
    if not isinstance(payload, Mapping):
        raise ValueError("acceptance report must be a JSON object")
    if payload.get("execution_mode") != "inline_isolated":
        raise ValueError("execution_mode must be inline_isolated")
    if not str(payload.get("run_id") or "").strip():
        raise ValueError("run_id is required")
    adapters = payload.get("adapters")
    if not isinstance(adapters, list) or not adapters:
        raise ValueError("controlled adapter manifest is required")
    fingerprint = payload.get("environment_fingerprint")
    if not isinstance(fingerprint, Mapping) or len(str(fingerprint.get("sha256") or "")) != 64:
        raise ValueError("environment fingerprint is required")
    boundaries = payload.get("boundaries")
    if not isinstance(boundaries, Mapping):
        raise ValueError("acceptance boundaries are required")
    if boundaries.get("production_worker_relay_topology_validated") is not False:
        raise ValueError("inline acceptance cannot prove production Worker/Relay topology")
    if boundaries.get("external_publication_performed") is not False:
        raise ValueError("inline acceptance cannot claim external publication")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an inline GEO acceptance report")
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.report.read_text(encoding="utf-8"))
        verify_report(payload)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Inline acceptance report failed: {error}")
        return 1
    print("Inline acceptance report passed: execution_mode=inline_isolated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
