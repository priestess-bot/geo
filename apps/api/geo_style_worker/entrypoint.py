"""Validate isolation controls before starting the dedicated Dramatiq consumer."""

from __future__ import annotations

import os

from geo_style_worker.preflight import STYLE_QUEUE, validate_style_browser_runtime


def main() -> None:
    validate_style_browser_runtime()
    os.execvp(
        "dramatiq",
        (
            "dramatiq",
            "geo_style_worker.tasks",
            "--queues",
            STYLE_QUEUE,
            "--processes",
            "1",
            "--threads",
            "1",
        ),
    )


if __name__ == "__main__":
    main()
