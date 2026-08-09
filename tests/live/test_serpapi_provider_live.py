"""Optional real SerpAPI Provider canary.

The test is intentionally skipped unless all Secret Store references needed by
the worker are present. A plaintext API key alone never enables this test.
"""

from __future__ import annotations

import argparse
import asyncio
import os

import pytest

from scripts.serpapi_provider_canary import _missing_environment, _run


@pytest.mark.live
def test_serpapi_provider_live_canary() -> None:
    missing = _missing_environment()
    if missing:
        pytest.skip("SerpAPI Secret Store canary inputs are not configured")
    query = os.getenv("SERPAPI_LIVE_QUERY", "ADVINSYS Australia")
    result = asyncio.run(
        _run(
            argparse.Namespace(
                query=query,
                location=os.getenv("SERPAPI_LIVE_LOCATION"),
                gl=os.getenv("SERPAPI_LIVE_GL", "au"),
                hl=os.getenv("SERPAPI_LIVE_HL", "en-AU"),
                google_domain=os.getenv("SERPAPI_LIVE_GOOGLE_DOMAIN", "google.com.au"),
                timeout_seconds=30.0,
                max_attempts=3,
            )
        )
    )
    assert result["status"] == "passed"
    assert result["provider"] == "serpapi"
    assert isinstance(result["block_count"], int)
