"""Start only the Browser Capture queue."""

from __future__ import annotations

import os

from geo_core.browser_capture.routing import BROWSER_CAPTURE_QUEUE


def main() -> None:
    os.execvp(
        "dramatiq",
        (
            "dramatiq",
            "geo_browser_capture_worker.tasks",
            "--queues",
            BROWSER_CAPTURE_QUEUE,
            "--processes",
            "1",
            "--threads",
            "1",
        ),
    )


if __name__ == "__main__":
    main()
