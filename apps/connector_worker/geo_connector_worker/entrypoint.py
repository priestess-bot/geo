"""Start only the Connector sync queue."""

from __future__ import annotations

import os

from geo_core.connectors.routing import CONNECTOR_SYNC_QUEUE


def main() -> None:
    os.execvp(
        "dramatiq",
        (
            "dramatiq",
            "geo_connector_worker.tasks",
            "--queues",
            CONNECTOR_SYNC_QUEUE,
            "--processes",
            "1",
            "--threads",
            "1",
        ),
    )


if __name__ == "__main__":
    main()
