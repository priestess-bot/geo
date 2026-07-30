from __future__ import annotations

from uuid import uuid4

from geo_worker import tasks


class _Broker:
    def __init__(self) -> None:
        self.messages: list[object] = []

    def enqueue(self, message: object) -> None:
        self.messages.append(message)


def test_maintenance_kinds_never_fall_back_to_the_general_worker(
    monkeypatch,
) -> None:
    broker = _Broker()
    monkeypatch.setattr(tasks, "broker", broker)
    monkeypatch.setattr(
        tasks.process_durable_job,
        "send",
        lambda *_args: (_ for _ in ()).throw(AssertionError("general queue used")),
    )
    job_id = uuid4()
    project_id = uuid4()

    for keyword, expected_queue in (
        ("workflow_c_maintenance", "workflow-c-maintenance"),
        (
            "recommendation_artifact_maintenance",
            "recommendation-artifact-maintenance",
        ),
        ("synthetic_artifact_maintenance", "synthetic-artifact-maintenance"),
        ("connector_sync", "connector-sync"),
        ("browser_capture", "browser-capture"),
    ):
        tasks.send_durable_job(
            job_id=job_id,
            project_id=project_id,
            style_collection=False,
            **{keyword: True},
        )
        message = broker.messages[-1]
        assert message.queue_name == expected_queue
        assert message.args == (str(job_id), str(project_id))


def test_dedicated_worker_routing_rejects_ambiguous_job_identity() -> None:
    from pytest import raises

    with raises(RuntimeError, match="two dedicated Workers"):
        tasks.send_durable_job(
            job_id=uuid4(),
            project_id=uuid4(),
            style_collection=True,
            synthetic_artifact_maintenance=True,
        )
