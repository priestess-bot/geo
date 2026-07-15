from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any


TASK_QUEUE_ENABLED_VALUES = {"1", "true", "yes", "on"}
TASK_QUEUE_ACTOR_NAMES = {
    "collection": "process_collection_queue",
    "knowledge": "process_knowledge_queue",
    "report": "process_report_export_queue",
}


@dataclass(frozen=True)
class TaskDispatchReceipt:
    task_name: str
    status: str
    message_id: str | None
    broker_url_configured: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def task_queue_enabled() -> bool:
    return os.getenv("GEO_TASK_QUEUE_ENABLED", "false").strip().lower() in TASK_QUEUE_ENABLED_VALUES


def task_queue_required() -> bool:
    deployment = os.getenv("GEO_DEPLOYMENT_ENVIRONMENT", "development").strip().lower()
    return deployment in {"production", "prod"} or (
        os.getenv("GEO_TASK_QUEUE_REQUIRED", "false").strip().lower() in TASK_QUEUE_ENABLED_VALUES
    )


def task_queue_broker_url() -> str:
    return os.getenv("GEO_TASK_QUEUE_BROKER_URL", "").strip()


def dispatch_background_task(task_name: str) -> TaskDispatchReceipt:
    actor_name = TASK_QUEUE_ACTOR_NAMES.get(task_name)
    if actor_name is None:
        raise ValueError(f"unsupported background task: {task_name}")
    broker_url = task_queue_broker_url()
    if not task_queue_enabled():
        if task_queue_required():
            raise RuntimeError("GEO_TASK_QUEUE_ENABLED=1 is required")
        return TaskDispatchReceipt(
            task_name=task_name,
            status="disabled",
            message_id=None,
            broker_url_configured=bool(broker_url),
        )
    if not broker_url:
        raise RuntimeError("GEO_TASK_QUEUE_BROKER_URL is required")
    try:
        from workers.task_queue import tasks

        actor = getattr(tasks, actor_name)
        message = actor.send()
    except (AttributeError, ImportError, OSError, RuntimeError) as exc:
        raise RuntimeError(f"unable to dispatch {task_name} task: {exc}") from exc
    return TaskDispatchReceipt(
        task_name=task_name,
        status="queued",
        message_id=str(message.message_id),
        broker_url_configured=True,
    )
