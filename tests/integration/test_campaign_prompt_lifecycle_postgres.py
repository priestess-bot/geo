from __future__ import annotations

import os
from queue import Queue
from threading import Barrier, Thread, current_thread
import time
from typing import Callable, TypeVar
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.placements.application import PlacementApplication
from geo_core.placements.domain import (
    ChannelReadinessReason,
    PlacementConflict,
    STANDARD_PLACEMENT_CHANNELS,
)
from geo_core.placements.default_prompts import default_output_schema
from geo_core.placements.postgres_repository import PsycopgPlacementRepository
from geo_core.placements.postgres_uow import placement_uow_factory
from geo_core.project_scope import set_project_scope
from tests.integration.placement_worker_support import cleanup_projects, login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]

T = TypeVar("T")


def test_release_and_binding_same_key_concurrency_replays_one_append() -> None:
    suffix = uuid4().hex[:10]
    app_login, password = f"geo_prompt_lifecycle_{suffix}", uuid4().hex
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                sql.Identifier(app_login), sql.Literal(password)
            )
        )
        ids = seed_project(admin, suffix=f"prompt-lifecycle-{suffix}")
    app_url = login_url(ADMIN_URL, user=app_login, password=password)
    application = PlacementApplication(
        placement_uow_factory(lambda: psycopg.connect(app_url))
    )
    try:
        destination = application.create_destination(
            project_id=ids["project"],
            publication_channel="reddit",
            destination_key=f"r/lifecycle-{suffix}",
            operation_mode="manual",
            destination_account_id=None,
            canonical_url="https://reddit.com",
        )
        campaign, opportunities = application.create_campaign(
            project_id=ids["project"],
            market_profile_id=ids["market"],
            primary_product_entity_id=ids["entity"],
            name="Prompt lifecycle concurrency",
            objective="recommendation_influence",
            actor_id=ids["owner"],
            destination_ids=(destination.id,),
            rationale="Concurrency contract",
        )
        skill = application.create_prompt_skill(
            project_id=ids["project"], skill_key=f"concurrency-{suffix}"
        )
        release = application.publish_skill_version(
            project_id=ids["project"],
            skill_id=skill.id,
            source="Use {{brief}} {{evidence}} {{destination_policy}}.",
            actor_id=ids["owner"],
            output_schema=default_output_schema(),
            client_variable_names=(),
        )

        state_key = f"approve-concurrently:{release.id}"
        with psycopg.connect(ADMIN_URL) as blocker:
            blocker.execute(
                "SELECT id FROM generation_template_releases WHERE id = %s FOR UPDATE",
                (release.id,),
            )
            states = _concurrent_commands(
                app_url=app_url,
                project_id=ids["project"],
                release_blocker=blocker,
                command=lambda repository: repository.transition_prompt_release_state(
                    project_id=ids["project"],
                    release_id=release.id,
                    expected_state_version=1,
                    target_status="approved",
                    reason="Concurrent approval",
                    actor_id=ids["owner"],
                    idempotency_key=state_key,
                ),
                name_prefix="state-racer-",
            )
        assert {item.id for item in states} == {release.id}
        assert {item.state_version for item in states} == {2}
        with psycopg.connect(app_url) as connection:
            set_project_scope(connection, ids["project"])
            repository = PsycopgPlacementRepository(connection)
            with pytest.raises(PlacementConflict, match="different input"):
                repository.transition_prompt_release_state(
                    project_id=ids["project"],
                    release_id=release.id,
                    expected_state_version=1,
                    target_status="approved",
                    reason="Different command hash",
                    actor_id=ids["owner"],
                    idempotency_key=state_key,
                )

        opportunity = opportunities[0]
        binding_key = f"bind-concurrently:{opportunity.id}"
        with psycopg.connect(ADMIN_URL) as blocker:
            blocker.execute(
                "SELECT id FROM placement_opportunities WHERE id = %s FOR UPDATE",
                (opportunity.id,),
            )
            bindings = _concurrent_commands(
                app_url=app_url,
                project_id=ids["project"],
                release_blocker=blocker,
                command=lambda repository: repository.bind_opportunity_prompt_release(
                    scope=_scope(ids["project"], opportunity.campaign_id),
                    opportunity_id=opportunity.id,
                    release_id=release.id,
                    expected_binding_version=1,
                    reason="Concurrent binding",
                    actor_id=ids["owner"],
                    idempotency_key=binding_key,
                ),
                name_prefix="binding-racer-",
            )
        assert len({item.id for item in bindings}) == 1
        assert {item.binding_version for item in bindings} == {2}
        with psycopg.connect(app_url) as connection:
            set_project_scope(connection, ids["project"])
            repository = PsycopgPlacementRepository(connection)
            with pytest.raises(PlacementConflict, match="different input"):
                repository.bind_opportunity_prompt_release(
                    scope=_scope(ids["project"], opportunity.campaign_id),
                    opportunity_id=opportunity.id,
                    release_id=release.id,
                    expected_binding_version=1,
                    reason="Different command hash",
                    actor_id=ids["owner"],
                    idempotency_key=binding_key,
                )
        readiness = application.get_campaign_placement_readiness(
            project_id=ids["project"], campaign_id=campaign.id
        )
        assert tuple(item.publication_channel for item in readiness.channels) == (
            STANDARD_PLACEMENT_CHANNELS
        )
        reddit = next(item for item in readiness.channels if item.publication_channel == "reddit")
        assert reddit.prompt_binding_id == bindings[0].id
        assert ChannelReadinessReason.PROMPT_BINDING_MISSING not in reddit.reasons

        revoked = application.transition_prompt_release(
            project_id=ids["project"],
            release_id=release.id,
            command="revoke",
            expected_state_version=2,
            reason="Retire the concurrency test Release",
            actor_id=ids["owner"],
            idempotency_key=f"revoke:{release.id}",
        )
        assert revoked.status.value == "revoked"
        with pytest.raises(PlacementConflict, match="approved Prompt Release"):
            application.bind_opportunity_prompt_release(
                project_id=ids["project"],
                campaign_id=campaign.id,
                opportunity_id=opportunity.id,
                release_id=release.id,
                expected_binding_version=2,
                reason="Must reject a revoked Release",
                actor_id=ids["owner"],
                idempotency_key=f"bind-revoked:{release.id}",
            )
        revoked_readiness = application.get_campaign_placement_readiness(
            project_id=ids["project"], campaign_id=campaign.id
        )
        reddit = next(
            item for item in revoked_readiness.channels if item.publication_channel == "reddit"
        )
        assert ChannelReadinessReason.PROMPT_RELEASE_REVOKED in reddit.reasons
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=[ids],
                tenant_ids=[ids["tenant"]],
                app_login=app_login,
            )


def _scope(project_id: UUID, campaign_id: UUID):
    from geo_core.placements.domain import CampaignScope

    return CampaignScope(project_id, campaign_id)


def _concurrent_commands(
    *,
    app_url: str,
    release_blocker: psycopg.Connection,
    command: Callable[[PsycopgPlacementRepository], T],
    name_prefix: str,
    project_id: UUID | None = None,
) -> list[T]:
    barrier = Barrier(3)
    results: Queue[T | BaseException] = Queue()

    def run() -> None:
        try:
            with psycopg.connect(
                app_url, application_name=f"{name_prefix}{current_thread().name}"
            ) as connection:
                if project_id is not None:
                    set_project_scope(connection, project_id)
                repository = PsycopgPlacementRepository(connection)
                barrier.wait()
                value = command(repository)
                connection.commit()
                results.put(value)
        except BaseException as exc:
            results.put(exc)

    threads = [Thread(target=run, name=str(index), daemon=True) for index in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    time.sleep(0.1)
    release_blocker.commit()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    values = [results.get_nowait() for _ in threads]
    errors = [value for value in values if isinstance(value, BaseException)]
    if errors:
        raise errors[0]
    return [value for value in values if not isinstance(value, BaseException)]
