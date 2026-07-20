"""Append-only Prompt Release lifecycle, Opportunity bindings, and readiness."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

from geo_core.placements.domain import (
    CampaignPlacementReadiness,
    CampaignScope,
    ChannelReadiness,
    ChannelReadinessReason,
    ConcurrencyConflict,
    OpportunityPromptReleaseBinding,
    PlacementConflict,
    PromptReleaseBindingStatus,
    PromptReleaseStatus,
    PromptReleaseView,
    STANDARD_PLACEMENT_CHANNELS,
    canonical_hash,
)


_RELEASE_VIEW_SQL = """
    SELECT release.id, release.project_id, release.skill_version_id,
           release.release_number, release.release_hash, version.source_text,
           release.system_template, release.user_template, release.variable_schema,
           release.output_schema, release.compiler_version,
           version.version_number AS skill_version,
           skill.skill_key,
           state.status, state.state_version, state.change_reason AS state_reason,
           approved.changed_by AS approved_by, approved.created_at AS approved_at,
           CASE WHEN state.status = 'revoked' THEN state.changed_by END AS revoked_by,
           CASE WHEN state.status = 'revoked' THEN state.created_at END AS revoked_at
    FROM generation_template_releases AS release
    JOIN prompt_skill_versions AS version
      ON version.id = release.skill_version_id AND version.project_id = release.project_id
    JOIN prompt_skills AS skill
      ON skill.id = version.skill_id AND skill.project_id = version.project_id
    JOIN current_generation_template_release_states AS state
      ON state.template_release_id = release.id AND state.project_id = release.project_id
    LEFT JOIN LATERAL (
      SELECT changed_by, created_at
      FROM generation_template_release_states AS event
      WHERE event.template_release_id = release.id AND event.project_id = release.project_id
        AND event.status = 'approved'
      ORDER BY event.state_version DESC LIMIT 1
    ) AS approved ON true
"""


class PostgresPromptLifecycleMixin:
    _db: Any

    def get_prompt_release_view(
        self, *, project_id: UUID, release_id: UUID
    ) -> PromptReleaseView | None:
        rows = _rows(
            self._db.execute(
                _RELEASE_VIEW_SQL
                + " WHERE release.project_id = %s AND release.id = %s",
                (project_id, release_id),
            )
        )
        return _release_view(rows[0]) if rows else None

    def transition_prompt_release_state(self, **values: Any) -> PromptReleaseView:
        command_hash = canonical_hash(
            {
                "release_id": str(values["release_id"]),
                "expected_state_version": values["expected_state_version"],
                "target_status": values["target_status"],
                "reason": values["reason"],
                "actor_id": str(values["actor_id"]),
            }
        )
        replay = self._idempotent_state(
            project_id=values["project_id"],
            idempotency_key=values["idempotency_key"],
            command_hash=command_hash,
        )
        if replay is not None:
            view = self.get_prompt_release_view(
                project_id=values["project_id"], release_id=replay
            )
            if view is None:
                raise RuntimeError("Prompt Release state replay lost its Release")
            return view
        release = _optional_row(
            self._db.execute(
                """SELECT id, project_id, skill_version_id, release_number, release_hash
                   FROM generation_template_releases
                   WHERE project_id = %s AND id = %s FOR UPDATE""",
                (values["project_id"], values["release_id"]),
            )
        )
        if release is None:
            raise PlacementConflict("Prompt Release does not exist in this Project")
        replay = self._idempotent_state(
            project_id=values["project_id"],
            idempotency_key=values["idempotency_key"],
            command_hash=command_hash,
        )
        if replay is not None:
            view = self.get_prompt_release_view(
                project_id=values["project_id"], release_id=replay
            )
            if view is None:
                raise RuntimeError("Prompt Release state replay lost its Release")
            return view
        state = _required_row(
            self._db.execute(
                """SELECT * FROM current_generation_template_release_states
                   WHERE project_id = %s AND template_release_id = %s""",
                (values["project_id"], values["release_id"]),
            )
        )
        if state["state_version"] != values["expected_state_version"]:
            raise ConcurrencyConflict("Prompt Release state changed concurrently")
        target = PromptReleaseStatus(str(values["target_status"]))
        allowed_target = {
            PromptReleaseStatus.DRAFT: PromptReleaseStatus.APPROVED,
            PromptReleaseStatus.APPROVED: PromptReleaseStatus.REVOKED,
        }.get(PromptReleaseStatus(str(state["status"])))
        if target != allowed_target:
            raise PlacementConflict("invalid Prompt Release state transition")
        inserted = _optional_row(
            self._db.execute(
                """INSERT INTO generation_template_release_states
                     (project_id, template_release_id, skill_version_id, release_number,
                      release_hash, state_version, previous_state_id, status, changed_by,
                      change_reason, idempotency_key, command_hash)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (project_id, idempotency_key)
                     WHERE idempotency_key IS NOT NULL DO NOTHING
                   RETURNING id""",
                (
                    release["project_id"],
                    release["id"],
                    release["skill_version_id"],
                    release["release_number"],
                    release["release_hash"],
                    state["state_version"] + 1,
                    state["id"],
                    target.value,
                    values["actor_id"],
                    values["reason"],
                    values["idempotency_key"],
                    command_hash,
                ),
            )
        )
        if inserted is None:
            replay = self._idempotent_state(
                project_id=values["project_id"],
                idempotency_key=values["idempotency_key"],
                command_hash=command_hash,
            )
            if replay is None:
                raise RuntimeError("Prompt Release state conflict lost its row")
            values["release_id"] = replay
        view = self.get_prompt_release_view(
            project_id=values["project_id"], release_id=values["release_id"]
        )
        if view is None:
            raise RuntimeError("Prompt Release disappeared after its state transition")
        return view

    def get_current_prompt_release_binding(
        self, *, scope: CampaignScope, opportunity_id: UUID
    ) -> OpportunityPromptReleaseBinding | None:
        rows = _rows(
            self._db.execute(
                """SELECT binding.*, skill.skill_key
                   FROM current_opportunity_prompt_release_bindings AS binding
                   LEFT JOIN prompt_skill_versions AS version
                     ON version.id = binding.skill_version_id
                    AND version.project_id = binding.project_id
                   LEFT JOIN prompt_skills AS skill
                     ON skill.id = version.skill_id AND skill.project_id = version.project_id
                   WHERE binding.project_id = %s AND binding.campaign_id = %s
                     AND binding.opportunity_id = %s""",
                (scope.project_id, scope.campaign_id, opportunity_id),
            )
        )
        return _binding(rows[0]) if rows else None

    def list_prompt_release_binding_history(
        self, *, scope: CampaignScope, opportunity_id: UUID
    ) -> tuple[OpportunityPromptReleaseBinding, ...]:
        return tuple(
            _binding(row)
            for row in _rows(
                self._db.execute(
                    """SELECT binding.*, skill.skill_key
                       FROM opportunity_prompt_release_bindings AS binding
                       LEFT JOIN prompt_skill_versions AS version
                         ON version.id = binding.skill_version_id
                        AND version.project_id = binding.project_id
                       LEFT JOIN prompt_skills AS skill
                         ON skill.id = version.skill_id
                        AND skill.project_id = version.project_id
                       WHERE binding.project_id = %s AND binding.campaign_id = %s
                         AND binding.opportunity_id = %s
                       ORDER BY binding.binding_version DESC, binding.id DESC""",
                    (scope.project_id, scope.campaign_id, opportunity_id),
                )
            )
        )

    def bind_opportunity_prompt_release(self, **values: Any) -> OpportunityPromptReleaseBinding:
        scope: CampaignScope = values["scope"]
        command_hash = canonical_hash(
            {
                "campaign_id": str(scope.campaign_id),
                "opportunity_id": str(values["opportunity_id"]),
                "release_id": str(values["release_id"]),
                "expected_binding_version": values["expected_binding_version"],
                "reason": values["reason"],
                "actor_id": str(values["actor_id"]),
            }
        )
        replay = self._idempotent_binding(
            project_id=scope.project_id,
            idempotency_key=values["idempotency_key"],
            command_hash=command_hash,
        )
        if replay is not None:
            return replay
        opportunity = _required_row(
            self._db.execute(
                """SELECT id, campaign_id, destination_id FROM placement_opportunities
                   WHERE id = %s AND project_id = %s AND campaign_id = %s FOR UPDATE""",
                (values["opportunity_id"], scope.project_id, scope.campaign_id),
            )
        )
        replay = self._idempotent_binding(
            project_id=scope.project_id,
            idempotency_key=values["idempotency_key"],
            command_hash=command_hash,
        )
        if replay is not None:
            return replay
        current = _required_row(
            self._db.execute(
                """SELECT * FROM current_opportunity_prompt_release_bindings
                   WHERE project_id = %s AND campaign_id = %s AND opportunity_id = %s""",
                (scope.project_id, scope.campaign_id, values["opportunity_id"]),
            )
        )
        if current["binding_version"] != values["expected_binding_version"]:
            raise ConcurrencyConflict("Opportunity Prompt binding changed concurrently")
        release = _optional_row(
            self._db.execute(
                """SELECT release.id, release.skill_version_id, release.release_number,
                          release.release_hash
                   FROM generation_template_releases AS release
                   JOIN current_generation_template_release_states AS state
                     ON state.template_release_id = release.id
                    AND state.project_id = release.project_id
                   WHERE release.project_id = %s AND release.id = %s
                     AND state.status = 'approved' FOR UPDATE OF release""",
                (scope.project_id, values["release_id"]),
            )
        )
        if release is None:
            raise PlacementConflict("Prompt Release is missing, revoked, or not approved")
        row = _optional_row(
            self._db.execute(
                """INSERT INTO opportunity_prompt_release_bindings
                     (project_id, campaign_id, opportunity_id, destination_id,
                      binding_version, previous_binding_id, binding_state,
                      template_release_id, skill_version_id, release_number, release_hash,
                      changed_by, change_reason, idempotency_key, command_hash)
                   VALUES (%s, %s, %s, %s, %s, %s, 'bound', %s, %s, %s, %s,
                           %s, %s, %s, %s)
                   ON CONFLICT (project_id, idempotency_key)
                     WHERE idempotency_key IS NOT NULL DO NOTHING
                   RETURNING *""",
                (
                    scope.project_id,
                    scope.campaign_id,
                    opportunity["id"],
                    opportunity["destination_id"],
                    current["binding_version"] + 1,
                    current["id"],
                    release["id"],
                    release["skill_version_id"],
                    release["release_number"],
                    release["release_hash"],
                    values["actor_id"],
                    values["reason"],
                    values["idempotency_key"],
                    command_hash,
                ),
            )
        )
        if row is None:
            replay = self._idempotent_binding(
                project_id=scope.project_id,
                idempotency_key=values["idempotency_key"],
                command_hash=command_hash,
            )
            if replay is None:
                raise RuntimeError("Prompt binding conflict lost its row")
            return replay
        result = self._idempotent_binding(
            project_id=scope.project_id,
            idempotency_key=values["idempotency_key"],
            command_hash=command_hash,
        )
        if result is None:
            raise RuntimeError("created Prompt binding could not be projected")
        return result

    def get_campaign_placement_readiness(
        self, *, scope: CampaignScope
    ) -> CampaignPlacementReadiness:
        rows = _rows(
            self._db.execute(
                """SELECT opportunity.id AS opportunity_id, opportunity.destination_id,
                          opportunity.status AS opportunity_status,
                          destination.publication_channel, destination.policy_status,
                          binding.id AS binding_id, binding.binding_state,
                          binding.template_release_id, binding.release_number,
                          binding.release_hash, release_state.status AS release_status,
                          brief.id AS brief_version_id,
                          evidence.id AS evidence_pack_attempt_id,
                          evidence.status AS evidence_status,
                          COALESCE(evidence.item_count, 0) AS evidence_item_count
                   FROM placement_opportunities AS opportunity
                   JOIN publication_destinations AS destination
                     ON destination.id = opportunity.destination_id
                    AND destination.project_id = opportunity.project_id
                   LEFT JOIN current_opportunity_prompt_release_bindings AS binding
                     ON binding.opportunity_id = opportunity.id
                    AND binding.project_id = opportunity.project_id
                    AND binding.campaign_id = opportunity.campaign_id
                   LEFT JOIN current_generation_template_release_states AS release_state
                     ON release_state.template_release_id = binding.template_release_id
                    AND release_state.project_id = binding.project_id
                   LEFT JOIN LATERAL (
                     SELECT version.id
                     FROM placement_brief_versions AS version
                     WHERE version.project_id = opportunity.project_id
                       AND version.campaign_id = opportunity.campaign_id
                       AND version.opportunity_id = opportunity.id
                     ORDER BY version.version_number DESC LIMIT 1
                   ) AS brief ON true
                   LEFT JOIN LATERAL (
                     SELECT attempt.id, attempt.status,
                            count(item.evidence_item_id)::integer AS item_count
                     FROM evidence_pack_attempts AS attempt
                     LEFT JOIN evidence_pack_items AS item
                       ON item.pack_attempt_id = attempt.id AND item.project_id = attempt.project_id
                     WHERE attempt.project_id = opportunity.project_id
                       AND attempt.campaign_id = opportunity.campaign_id
                       AND attempt.opportunity_id = opportunity.id
                       AND attempt.brief_version_id = brief.id
                     GROUP BY attempt.id
                     ORDER BY attempt.attempt_number DESC LIMIT 1
                   ) AS evidence ON true
                   WHERE opportunity.project_id = %s AND opportunity.campaign_id = %s
                     AND opportunity.status <> 'cancelled'
                   ORDER BY destination.publication_channel, opportunity.created_at,
                            opportunity.id""",
                (scope.project_id, scope.campaign_id),
            )
        )
        by_channel: dict[str, list[dict[str, Any]]] = {
            channel: [] for channel in STANDARD_PLACEMENT_CHANNELS
        }
        for row in rows:
            if row["publication_channel"] in by_channel:
                by_channel[row["publication_channel"]].append(row)
        channels = tuple(
            _channel_readiness(channel, by_channel[channel])
            for channel in STANDARD_PLACEMENT_CHANNELS
        )
        return CampaignPlacementReadiness(scope.project_id, scope.campaign_id, channels)

    def _idempotent_state(
        self, *, project_id: UUID, idempotency_key: str, command_hash: str
    ) -> UUID | None:
        rows = _rows(
            self._db.execute(
                """SELECT template_release_id, command_hash
                   FROM generation_template_release_states
                   WHERE project_id = %s AND idempotency_key = %s""",
                (project_id, idempotency_key),
            )
        )
        if not rows:
            return None
        if rows[0]["command_hash"] != command_hash:
            raise PlacementConflict("idempotency key was already used with different input")
        return rows[0]["template_release_id"]

    def _idempotent_binding(
        self, *, project_id: UUID, idempotency_key: str, command_hash: str
    ) -> OpportunityPromptReleaseBinding | None:
        rows = _rows(
            self._db.execute(
                """SELECT binding.*, skill.skill_key
                   FROM opportunity_prompt_release_bindings AS binding
                   LEFT JOIN prompt_skill_versions AS version
                     ON version.id = binding.skill_version_id
                    AND version.project_id = binding.project_id
                   LEFT JOIN prompt_skills AS skill
                     ON skill.id = version.skill_id AND skill.project_id = version.project_id
                   WHERE binding.project_id = %s AND binding.idempotency_key = %s""",
                (project_id, idempotency_key),
            )
        )
        if not rows:
            return None
        if rows[0]["command_hash"] != command_hash:
            raise PlacementConflict("idempotency key was already used with different input")
        return _binding(rows[0])


def _release_view(row: Mapping[str, Any]) -> PromptReleaseView:
    return PromptReleaseView(
        **{
            **dict(row),
            "status": PromptReleaseStatus(str(row["status"])),
        }
    )


def _binding(row: Mapping[str, Any]) -> OpportunityPromptReleaseBinding:
    return OpportunityPromptReleaseBinding(
        id=row["id"],
        project_id=row["project_id"],
        campaign_id=row["campaign_id"],
        opportunity_id=row["opportunity_id"],
        destination_id=row["destination_id"],
        binding_version=row["binding_version"],
        previous_binding_id=row.get("previous_binding_id"),
        status=PromptReleaseBindingStatus(str(row["binding_state"])),
        template_release_id=row.get("template_release_id"),
        skill_key=row.get("skill_key"),
        skill_version_id=row.get("skill_version_id"),
        release_version=row.get("release_number"),
        release_hash=row.get("release_hash"),
        changed_by=row["changed_by"],
        changed_at=row["created_at"],
        reason=row.get("change_reason"),
    )


def _channel_readiness(channel: str, rows: list[dict[str, Any]]) -> ChannelReadiness:
    if not rows:
        return ChannelReadiness(
            channel, False, (ChannelReadinessReason.MISSING_OPPORTUNITY,)
        )
    if len(rows) > 1:
        return ChannelReadiness(
            channel, False, (ChannelReadinessReason.DUPLICATE_CHANNEL,)
        )
    row = rows[0]
    reasons: list[ChannelReadinessReason] = []
    status = row["opportunity_status"]
    if status == "blocked":
        reasons.append(ChannelReadinessReason.OPPORTUNITY_BLOCKED)
    elif status not in {"briefing", "in_progress"}:
        reasons.append(ChannelReadinessReason.OPPORTUNITY_NOT_GENERATION_READY)
    if row["policy_status"] == "unreviewed":
        reasons.append(ChannelReadinessReason.DESTINATION_POLICY_MISSING)
    elif row["policy_status"] != "approved":
        reasons.append(ChannelReadinessReason.DESTINATION_POLICY_NOT_APPROVED)
    if row.get("binding_id") is None or row.get("binding_state") != "bound":
        reasons.append(ChannelReadinessReason.PROMPT_BINDING_MISSING)
    elif row.get("release_status") == "draft":
        reasons.append(ChannelReadinessReason.PROMPT_RELEASE_DRAFT)
    elif row.get("release_status") == "revoked":
        reasons.append(ChannelReadinessReason.PROMPT_RELEASE_REVOKED)
    if row.get("brief_version_id") is None:
        reasons.append(ChannelReadinessReason.BRIEF_MISSING)
    elif row.get("evidence_pack_attempt_id") is None:
        reasons.append(ChannelReadinessReason.EVIDENCE_PACK_MISSING)
    elif row.get("evidence_status") != "ready":
        reasons.append(ChannelReadinessReason.EVIDENCE_PACK_NOT_READY)
    elif row.get("evidence_item_count", 0) < 1:
        reasons.append(ChannelReadinessReason.EVIDENCE_ITEMS_MISSING)
    return ChannelReadiness(
        publication_channel=channel,
        ready=not reasons,
        reasons=tuple(reasons),
        opportunity_id=row["opportunity_id"],
        destination_id=row["destination_id"],
        prompt_binding_id=row.get("binding_id"),
        template_release_id=row.get("template_release_id"),
        release_version=row.get("release_number"),
        release_hash=row.get("release_hash"),
        brief_version_id=row.get("brief_version_id"),
        evidence_pack_attempt_id=row.get("evidence_pack_attempt_id"),
    )


def _rows(cursor: Any) -> list[dict[str, Any]]:
    records = cursor.fetchall()
    if not records:
        return []
    if isinstance(records[0], Mapping):
        return [dict(record) for record in records]
    names = [item.name for item in cursor.description]
    return [dict(zip(names, record, strict=True)) for record in records]


def _required_row(cursor: Any) -> dict[str, Any]:
    rows = _rows(cursor)
    if not rows:
        raise RuntimeError("expected PostgreSQL row was not returned")
    return rows[0]


def _optional_row(cursor: Any) -> dict[str, Any] | None:
    rows = _rows(cursor)
    return rows[0] if rows else None
