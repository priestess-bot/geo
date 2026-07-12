from __future__ import annotations

import argparse
import json
import time

from geno_core.task_queue import dispatch_background_task


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-dispatch durable PostgreSQL jobs to Dramatiq after restarts and retry delays."
    )
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        receipts = [
            dispatch_background_task(task_name).to_dict()
            for task_name in ("collection", "knowledge", "report")
        ]
        print(json.dumps({"status": "dispatched", "receipts": receipts}, ensure_ascii=False), flush=True)
        if args.once:
            return 0
        time.sleep(max(5.0, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
