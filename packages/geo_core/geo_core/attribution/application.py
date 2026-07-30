"""Minimal first-party collection and deterministic attribution snapshots."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import hmac
import secrets
from typing import Any, cast
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from geo_core.connectors.contracts import canonical_hash
from geo_core.project_scope import set_project_scope


class AttributionError(RuntimeError):
    """Attribution input is unsafe, incomplete, or conflicts with frozen evidence."""


_UTM_KEYS = frozenset({"source", "medium", "campaign", "term", "content"})
_BUSINESS_KINDS = frozenset({"lead", "stage", "conversion", "deal", "revenue"})


class AttributionService:
    def __init__(
        self,
        *,
        connect: Callable[[], Any],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connect = connect
        self._clock = clock

    def inventory(self, *, project_id: UUID) -> Mapping[str, object]:
        count_tables = {
            "traces": "attribution_trace_links",
            "sessions": "attribution_sessions",
            "touches": "attribution_touches",
            "leads": "attribution_leads",
            "conversions": "attribution_conversions",
            "deals": "attribution_deals",
            "revenues": "attribution_revenues",
        }
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            policies = connection.execute(
                """SELECT * FROM attribution_policies
                    WHERE project_id = %s ORDER BY version DESC""",
                (project_id,),
            ).fetchall()
            collectors = connection.execute(
                """SELECT id, project_id, name, allowed_origins, event_schema_version,
                          sdk_release, consent_mode, status, created_at
                     FROM attribution_collectors WHERE project_id = %s
                    ORDER BY created_at DESC, id DESC""",
                (project_id,),
            ).fetchall()
            snapshots = connection.execute(
                """SELECT *, false AS replayed FROM attribution_snapshots
                    WHERE project_id = %s ORDER BY created_at DESC, id DESC LIMIT 50""",
                (project_id,),
            ).fetchall()
            counts = {
                name: connection.execute(
                    f"SELECT count(*) AS total FROM {table} WHERE project_id = %s",
                    (project_id,),
                ).fetchone()["total"]
                for name, table in count_tables.items()
            }
        return {
            "policies": [dict(row) for row in policies],
            "collectors": [dict(row) for row in collectors],
            "counts": counts,
            "snapshots": [dict(row) for row in snapshots],
        }

    def create_policy(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        last_click_days: int = 30,
        assisted_days: int = 90,
        eligible_touch_types: Sequence[str] = ("page_view", "click"),
    ) -> Mapping[str, object]:
        if not 1 <= last_click_days <= assisted_days <= 730:
            raise AttributionError("Attribution windows are invalid")
        eligible = tuple(dict.fromkeys(eligible_touch_types))
        if not eligible or set(eligible) - {"page_view", "click"}:
            raise AttributionError("Eligible touch types are invalid")
        value = {
            "last_click_days": last_click_days,
            "assisted_days": assisted_days,
            "direct_rule": "only_without_eligible_touch",
            "eligible_touch_types": eligible,
        }
        now = self._clock()
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            replay = connection.execute(
                """SELECT * FROM attribution_policies
                    WHERE project_id = %s AND policy_hash = %s""",
                (project_id, canonical_hash(value)),
            ).fetchone()
            if replay is not None:
                return dict(replay)
            version = connection.execute(
                """SELECT coalesce(max(version), 0) + 1 AS version
                     FROM attribution_policies WHERE project_id = %s""",
                (project_id,),
            ).fetchone()["version"]
            connection.execute(
                """UPDATE attribution_policies
                      SET status = 'retired', retired_at = %s
                    WHERE project_id = %s AND status = 'active'""",
                (now, project_id),
            )
            row = connection.execute(
                """INSERT INTO attribution_policies(
                       id, project_id, version, last_click_days, assisted_days,
                       direct_rule, eligible_touch_types, policy_hash, status,
                       created_by, created_at
                   ) VALUES (%s, %s, %s, %s, %s, 'only_without_eligible_touch',
                             %s, %s, 'active', %s, %s) RETURNING *""",
                (
                    uuid4(), project_id, version, last_click_days, assisted_days,
                    list(eligible), canonical_hash(value), actor_id, now,
                ),
            ).fetchone()
        return dict(row)

    def create_collector(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        name: str,
        allowed_origins: Sequence[str],
        event_schema_version: str = "geo-attribution-event-v1",
        sdk_release: str = "geo-browser-sdk-v1",
    ) -> Mapping[str, object]:
        origins = tuple(dict.fromkeys(origin.rstrip("/") for origin in allowed_origins))
        if not name.strip() or not origins or any(not item.startswith("https://") for item in origins):
            raise AttributionError("Collector name and HTTPS allowed origins are required")
        write_key = secrets.token_urlsafe(32)
        now, collector_id = self._clock(), uuid4()
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """INSERT INTO attribution_collectors(
                       id, project_id, name, write_key_hash, allowed_origins,
                       event_schema_version, sdk_release, consent_mode, status,
                       created_by, created_at
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'explicit', 'active', %s, %s)
                   RETURNING id, project_id, name, allowed_origins, event_schema_version,
                             sdk_release, consent_mode, status, created_at""",
                (
                    collector_id, project_id, name.strip(), _hash(write_key), list(origins),
                    event_schema_version, sdk_release, actor_id, now,
                ),
            ).fetchone()
        return {**dict(row), "write_key": write_key}

    def issue_trace(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        campaign_id: UUID,
        content_asset_key: str,
        verified_url: str,
        question_set_id: UUID | None = None,
        package_version_id: UUID | None = None,
        ttl_days: int = 180,
    ) -> Mapping[str, object]:
        if not content_asset_key.strip() or not verified_url.startswith("https://"):
            raise AttributionError("Content asset and verified HTTPS URL are required")
        if not 1 <= ttl_days <= 730:
            raise AttributionError("Trace lifetime is invalid")
        token, trace_id, now = secrets.token_urlsafe(32), uuid4(), self._clock()
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            campaign = connection.execute(
                "SELECT 1 FROM geo_campaigns WHERE project_id = %s AND id = %s",
                (project_id, campaign_id),
            ).fetchone()
            if campaign is None:
                raise AttributionError("Campaign was not found")
            if question_set_id is not None and connection.execute(
                """SELECT 1 FROM knowledge_question_sets
                    WHERE project_id = %s AND campaign_id = %s AND id = %s""",
                (project_id, campaign_id, question_set_id),
            ).fetchone() is None:
                raise AttributionError("Question Set does not belong to the Campaign")
            if package_version_id is not None and connection.execute(
                """SELECT 1 FROM placement_package_versions
                    WHERE project_id = %s AND campaign_id = %s AND id = %s""",
                (project_id, campaign_id, package_version_id),
            ).fetchone() is None:
                raise AttributionError("Package Version does not belong to the Campaign")
            row = connection.execute(
                """INSERT INTO attribution_trace_links(
                       id, project_id, token_hash, campaign_id, question_set_id,
                       package_version_id, content_asset_key, verified_url,
                       issued_at, expires_at, created_by
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id, project_id, campaign_id, question_set_id,
                             package_version_id, content_asset_key, verified_url,
                             issued_at, expires_at""",
                (
                    trace_id, project_id, _hash(token), campaign_id, question_set_id,
                    package_version_id, content_asset_key.strip(), verified_url,
                    now, now + timedelta(days=ttl_days), actor_id,
                ),
            ).fetchone()
        return {**dict(row), "trace_token": token}

    def collect(
        self,
        *,
        project_id: UUID,
        collector_id: UUID,
        write_key: str,
        origin: str,
        client_session_id: UUID,
        source_event_id: str,
        event_type: str,
        occurred_at: datetime,
        consent: bool,
        consent_schema_version: str,
        trace_token: str | None,
        utm: Mapping[str, str],
    ) -> Mapping[str, object]:
        if not consent:
            raise AttributionError("Explicit attribution consent is required")
        if event_type not in {"session_start", "page_view", "click", "direct"}:
            raise AttributionError("Unsupported first-party event type")
        if not source_event_id.strip() or set(utm) - _UTM_KEYS:
            raise AttributionError("Event ID or UTM fields are invalid")
        now = self._clock()
        if occurred_at > now + timedelta(minutes=5):
            raise AttributionError("Event occurred_at is too far in the future")
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            collector = connection.execute(
                """SELECT * FROM attribution_collectors
                    WHERE project_id = %s AND id = %s AND status = 'active'""",
                (project_id, collector_id),
            ).fetchone()
            if collector is None or not hmac.compare_digest(
                collector["write_key_hash"], _hash(write_key)
            ):
                raise AttributionError("Collector credentials are invalid")
            normalized_origin = origin.rstrip("/")
            if normalized_origin not in collector["allowed_origins"]:
                raise AttributionError("Collector origin is not allowed")
            trace = None
            if trace_token:
                trace = connection.execute(
                    """SELECT * FROM attribution_trace_links
                        WHERE project_id = %s AND token_hash = %s AND expires_at >= %s""",
                    (project_id, _hash(trace_token), occurred_at),
                ).fetchone()
                if trace is None:
                    raise AttributionError("Trace token is invalid or expired")
            if event_type in {"page_view", "click"} and trace is None:
                raise AttributionError("GEO page and click events require an exact trace")
            if event_type == "direct" and (trace is not None or utm):
                raise AttributionError("Direct events cannot carry trace or UTM attribution")
            session_id = uuid4()
            session = connection.execute(
                """INSERT INTO attribution_sessions(
                       id, project_id, collector_id, client_session_id, started_at,
                       last_seen_at, received_at, consent_schema_version,
                       event_schema_version, sdk_release, source_type, lineage
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                             'first_party_browser', %s)
                   ON CONFLICT (project_id, collector_id, client_session_id) DO UPDATE
                       SET last_seen_at = greatest(attribution_sessions.last_seen_at,
                                                  EXCLUDED.last_seen_at)
                   RETURNING *""",
                (
                    session_id, project_id, collector_id, client_session_id,
                    occurred_at, occurred_at, now, consent_schema_version,
                    collector["event_schema_version"], collector["sdk_release"],
                    Jsonb({"collector_id": str(collector_id)}),
                ),
            ).fetchone()
            if event_type == "session_start":
                return {
                    "project_id": project_id,
                    "session_id": session["id"],
                    "replayed": session["id"] != session_id,
                }
            touch_id = uuid4()
            touch = connection.execute(
                """INSERT INTO attribution_touches(
                       id, project_id, session_id, source_event_id, touch_type,
                       occurred_at, received_at, trace_link_id, utm, source_type,
                       schema_version, lineage
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                             'first_party_browser', %s, %s)
                   ON CONFLICT (project_id, source_event_id) DO NOTHING
                   RETURNING *""",
                (
                    touch_id, project_id, session["id"], source_event_id, event_type,
                    occurred_at, now, trace["id"] if trace else None,
                    Jsonb(dict(utm)), collector["event_schema_version"],
                    Jsonb({"collector_id": str(collector_id)}),
                ),
            ).fetchone()
            replayed = touch is None
            if touch is None:
                touch = connection.execute(
                    """SELECT * FROM attribution_touches
                        WHERE project_id = %s AND source_event_id = %s""",
                    (project_id, source_event_id),
                ).fetchone()
                if (
                    touch is None
                    or touch["session_id"] != session["id"]
                    or touch["touch_type"] != event_type
                    or touch["occurred_at"] != occurred_at
                    or touch["trace_link_id"] != (trace["id"] if trace else None)
                    or touch["utm"] != dict(utm)
                ):
                    raise AttributionError("Source event ID was reused with different input")
        return {
            "project_id": project_id,
            "session_id": session["id"],
            "touch_id": touch["id"],
            "replayed": replayed,
        }

    def record_business_event(
        self,
        *,
        project_id: UUID,
        kind: str,
        source_event_id: str,
        parent_id: UUID,
        occurred_at: datetime,
        local_business_id: str | None = None,
        label: str | None = None,
        currency: str | None = None,
        amount: Decimal | None = None,
        source_type: str = "admin",
        schema_version: str = "attribution-business-v1",
        import_id: UUID | None = None,
    ) -> Mapping[str, object]:
        if kind not in _BUSINESS_KINDS or source_type not in {"admin", "file_import"}:
            raise AttributionError("Business event kind or source is invalid")
        now, event_id = self._clock(), uuid4()
        table, parent_column, extra_columns, extra_values = _business_shape(
            kind=kind,
            local_business_id=local_business_id,
            label=label,
            currency=currency,
            amount=amount,
        )
        columns = [
            "id", "project_id", parent_column, "source_event_id", *extra_columns,
            "occurred_at", "received_at", "source_type", "schema_version",
            "import_id", "lineage",
        ]
        values = [
            event_id, project_id, parent_id, source_event_id, *extra_values,
            occurred_at, now, source_type, schema_version, import_id,
            Jsonb({"parent_id": str(parent_id)}),
        ]
        placeholders = ", ".join(["%s"] * len(values))
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                f"""INSERT INTO {table}({', '.join(columns)})
                     VALUES ({placeholders})
                     ON CONFLICT (project_id, source_event_id) DO NOTHING
                     RETURNING *""",  # table and columns come from the closed map above
                values,
            ).fetchone()
            replayed = row is None
            if row is None:
                row = connection.execute(
                    f"""SELECT * FROM {table}
                        WHERE project_id = %s AND source_event_id = %s""",
                    (project_id, source_event_id),
                ).fetchone()
                if row is None or row[parent_column] != parent_id:
                    raise AttributionError("Business event ID was reused with different lineage")
        return {**dict(row), "replayed": replayed}

    def import_business_rows(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        template_schema_version: str,
        rows: Sequence[Mapping[str, object]],
    ) -> Mapping[str, object]:
        """Validate and atomically persist a bounded, replayable business-event file."""
        if not template_schema_version.strip() or not 1 <= len(rows) <= 1_000:
            raise AttributionError("Import schema and between 1 and 1000 rows are required")
        file_value = {
            "template_schema_version": template_schema_version,
            "rows": [dict(row) for row in rows],
        }
        file_hash, import_id, now = canonical_hash(file_value), uuid4(), self._clock()
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            replay = connection.execute(
                """SELECT * FROM attribution_imports
                    WHERE project_id = %s AND file_hash = %s""",
                (project_id, file_hash),
            ).fetchone()
            if replay is not None:
                return {**dict(replay), "replayed": True}

            accepted: list[dict[str, object]] = []
            rejected: list[dict[str, object]] = []
            staged_ids: dict[UUID, str] = {}
            source_ids: set[tuple[str, str]] = set()
            for index, raw in enumerate(rows, start=1):
                try:
                    normalized = _validate_import_row(
                        connection=connection,
                        project_id=project_id,
                        row=raw,
                        staged_ids=staged_ids,
                        source_ids=source_ids,
                    )
                except AttributionError as error:
                    rejected.append(
                        {"row": index, "code": "invalid_row", "detail": str(error)}
                    )
                    continue
                accepted.append({"row": index, **normalized})
                staged_ids[cast(UUID, normalized["id"])] = cast(str, normalized["kind"])
                source_ids.add(
                    (cast(str, normalized["kind"]), cast(str, normalized["source_event_id"]))
                )

            result = {
                "schema_version": template_schema_version,
                "accepted": [
                    {"row": item["row"], "id": str(item["id"]), "kind": item["kind"]}
                    for item in accepted
                ],
                "rejected": rejected,
            }
            connection.execute(
                """INSERT INTO attribution_imports(
                       id, project_id, template_schema_version, file_hash, row_count,
                       accepted_count, rejected_count, requested_by, requested_at, result
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    import_id, project_id, template_schema_version, file_hash, len(rows),
                    len(accepted), len(rejected), actor_id, now, Jsonb(result),
                ),
            )
            for item in accepted:
                _insert_imported_event(
                    connection=connection,
                    project_id=project_id,
                    import_id=import_id,
                    received_at=now,
                    schema_version=template_schema_version,
                    row=item,
                )
            stored = connection.execute(
                """SELECT * FROM attribution_imports
                    WHERE project_id = %s AND id = %s""",
                (project_id, import_id),
            ).fetchone()
        return {**dict(stored), "replayed": False}

    def create_snapshot(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        cutoff_at: datetime,
        policy_id: UUID | None = None,
    ) -> Mapping[str, object]:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            policy = connection.execute(
                """SELECT * FROM attribution_policies
                    WHERE project_id = %s AND (%s::uuid IS NULL OR id = %s)
                    ORDER BY (status = 'active') DESC, version DESC LIMIT 1""",
                (project_id, policy_id, policy_id),
            ).fetchone()
            if policy is None:
                raise AttributionError("Attribution policy was not found")
            revenues = connection.execute(
                """SELECT revenue.id AS revenue_id, revenue.source_event_id,
                          revenue.amount, revenue.currency, revenue.occurred_at,
                          deal.id AS deal_id, conversion.id AS conversion_id,
                          conversion.occurred_at AS conversion_at, lead.id AS lead_id,
                          session.id AS session_id
                     FROM attribution_revenues revenue
                     JOIN attribution_deals deal ON deal.project_id = revenue.project_id
                                                AND deal.id = revenue.deal_id
                     JOIN attribution_conversions conversion
                       ON conversion.project_id = deal.project_id
                      AND conversion.id = deal.conversion_id
                     JOIN attribution_leads lead ON lead.project_id = conversion.project_id
                                                AND lead.id = conversion.lead_id
                     JOIN attribution_sessions session ON session.project_id = lead.project_id
                                                      AND session.id = lead.session_id
                    WHERE revenue.project_id = %s AND revenue.occurred_at <= %s
                    ORDER BY revenue.occurred_at, revenue.id""",
                (project_id, cutoff_at),
            ).fetchall()
            entries: list[dict[str, object]] = []
            membership: list[dict[str, object]] = []
            for revenue in revenues:
                touches = connection.execute(
                    """SELECT touch.*, trace.campaign_id, trace.question_set_id,
                              trace.package_version_id, trace.content_asset_key,
                              trace.verified_url
                         FROM attribution_touches touch
                         LEFT JOIN attribution_trace_links trace
                           ON trace.project_id = touch.project_id
                          AND trace.id = touch.trace_link_id
                        WHERE touch.project_id = %s AND touch.session_id = %s
                          AND touch.occurred_at <= %s
                        ORDER BY touch.occurred_at, touch.id""",
                    (project_id, revenue["session_id"], revenue["conversion_at"]),
                ).fetchall()
                entry = _attribute(revenue, touches, policy)
                entries.append(entry)
                membership.append(
                    {
                        "revenue_id": str(revenue["revenue_id"]),
                        "touch_ids": [str(touch["id"]) for touch in touches],
                    }
                )
            input_value = {
                "policy_hash": policy["policy_hash"],
                "cutoff_at": cutoff_at.isoformat(),
                "membership": membership,
            }
            result = {
                "methodology": "observational_association_not_causation",
                "policy": {
                    "id": str(policy["id"]),
                    "version": policy["version"],
                    "last_click_days": policy["last_click_days"],
                    "assisted_days": policy["assisted_days"],
                },
                "cutoff_at": cutoff_at.isoformat(),
                "entries": entries,
            }
            input_hash, result_hash = canonical_hash(input_value), canonical_hash(result)
            snapshot_id, now = uuid4(), self._clock()
            row = connection.execute(
                """INSERT INTO attribution_snapshots(
                       id, project_id, policy_id, cutoff_at, input_hash, result,
                       result_hash, created_by, created_at
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (project_id, input_hash) DO NOTHING
                   RETURNING *""",
                (
                    snapshot_id, project_id, policy["id"], cutoff_at, input_hash,
                    Jsonb(result), result_hash, actor_id, now,
                ),
            ).fetchone()
            replayed = row is None
            if row is None:
                row = connection.execute(
                    """SELECT * FROM attribution_snapshots
                        WHERE project_id = %s AND input_hash = %s""",
                    (project_id, input_hash),
                ).fetchone()
                if row is None or row["result_hash"] != result_hash:
                    raise AttributionError("Attribution snapshot replay is inconsistent")
        return {**dict(row), "replayed": replayed}


def _business_shape(
    *, kind: str, local_business_id: str | None, label: str | None,
    currency: str | None, amount: Decimal | None,
) -> tuple[str, str, list[str], list[object]]:
    if kind == "lead":
        if not local_business_id:
            raise AttributionError("Lead local business ID is required")
        return "attribution_leads", "session_id", ["local_business_id"], [local_business_id]
    if kind == "stage":
        if not label:
            raise AttributionError("Stage label is required")
        return "attribution_stages", "lead_id", ["stage"], [label]
    if kind == "conversion":
        if not label:
            raise AttributionError("Conversion kind is required")
        return "attribution_conversions", "lead_id", ["conversion_kind"], [label]
    if kind == "deal":
        if not local_business_id or currency is None or amount is None:
            raise AttributionError("Deal ID, currency, and amount are required")
        return (
            "attribution_deals", "conversion_id",
            ["local_business_id", "currency", "amount"],
            [local_business_id, currency.upper(), amount],
        )
    if currency is None or amount is None or label not in {"booked", "recognized"}:
        raise AttributionError("Revenue kind, currency, and amount are required")
    return (
        "attribution_revenues", "deal_id", ["revenue_kind", "currency", "amount"],
        [label, currency.upper(), amount],
    )


_PARENT_SHAPES = {
    "lead": ("attribution_sessions", None),
    "stage": ("attribution_leads", "lead"),
    "conversion": ("attribution_leads", "lead"),
    "deal": ("attribution_conversions", "conversion"),
    "revenue": ("attribution_deals", "deal"),
}


def _validate_import_row(
    *, connection: Any, project_id: UUID, row: Mapping[str, object],
    staged_ids: Mapping[UUID, str], source_ids: set[tuple[str, str]],
) -> dict[str, object]:
    try:
        entity_id = row["id"]
        parent_id = row["parent_id"]
        kind = row["kind"]
        source_event_id = row["source_event_id"]
        occurred_at = row["occurred_at"]
    except KeyError as error:
        raise AttributionError(f"Required field {error.args[0]} is missing") from error
    if not isinstance(entity_id, UUID) or entity_id.int == 0 or entity_id in staged_ids:
        raise AttributionError("Event ID is invalid or duplicated in this import")
    if not isinstance(parent_id, UUID) or parent_id.int == 0:
        raise AttributionError("Parent ID is invalid")
    if not isinstance(kind, str) or kind not in _BUSINESS_KINDS or not isinstance(source_event_id, str):
        raise AttributionError("Business event kind or source event ID is invalid")
    if not source_event_id.strip() or (kind, source_event_id) in source_ids:
        raise AttributionError("Source event ID is empty or duplicated in this import")
    if not isinstance(occurred_at, datetime) or occurred_at.utcoffset() is None:
        raise AttributionError("occurred_at must include a timezone")
    local_business_id = row.get("local_business_id")
    label = row.get("label")
    currency = row.get("currency")
    amount = row.get("amount")
    if amount is not None and not isinstance(amount, Decimal):
        raise AttributionError("Amount must be a decimal value")
    _business_shape(
        kind=kind,
        local_business_id=cast(str | None, local_business_id),
        label=cast(str | None, label),
        currency=cast(str | None, currency),
        amount=amount,
    )
    parent_table, staged_parent_kind = _PARENT_SHAPES[kind]
    parent_is_staged = staged_parent_kind is not None and staged_ids.get(parent_id) == staged_parent_kind
    if not parent_is_staged and connection.execute(
        f"SELECT 1 FROM {parent_table} WHERE project_id = %s AND id = %s",
        (project_id, parent_id),
    ).fetchone() is None:
        raise AttributionError("Parent entity was not found or appears after this row")
    table, _, _, _ = _business_shape(
        kind=kind,
        local_business_id=cast(str | None, local_business_id),
        label=cast(str | None, label),
        currency=cast(str | None, currency),
        amount=amount,
    )
    if connection.execute(
        f"SELECT 1 FROM {table} WHERE project_id = %s AND source_event_id = %s",
        (project_id, source_event_id),
    ).fetchone() is not None:
        raise AttributionError("Source event ID already exists")
    return {
        "id": entity_id, "kind": kind, "source_event_id": source_event_id.strip(),
        "parent_id": parent_id, "occurred_at": occurred_at,
        "local_business_id": local_business_id, "label": label,
        "currency": cast(str, currency).upper() if currency else None, "amount": amount,
    }


def _insert_imported_event(
    *, connection: Any, project_id: UUID, import_id: UUID, received_at: datetime,
    schema_version: str, row: Mapping[str, object],
) -> None:
    kind = cast(str, row["kind"])
    table, parent_column, extra_columns, extra_values = _business_shape(
        kind=kind,
        local_business_id=cast(str | None, row.get("local_business_id")),
        label=cast(str | None, row.get("label")),
        currency=cast(str | None, row.get("currency")),
        amount=cast(Decimal | None, row.get("amount")),
    )
    columns = [
        "id", "project_id", parent_column, "source_event_id", *extra_columns,
        "occurred_at", "received_at", "source_type", "schema_version", "import_id", "lineage",
    ]
    values = [
        row["id"], project_id, row["parent_id"], row["source_event_id"], *extra_values,
        row["occurred_at"], received_at, "file_import", schema_version, import_id,
        Jsonb({"import_id": str(import_id), "parent_id": str(row["parent_id"])}),
    ]
    connection.execute(
        f"INSERT INTO {table}({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(values))})",
        values,
    )


def _attribute(
    revenue: Mapping[str, object],
    touches: Sequence[Mapping[str, object]],
    policy: Mapping[str, object],
) -> dict[str, object]:
    conversion_at = revenue["conversion_at"]
    assert isinstance(conversion_at, datetime)
    eligible_types = set(cast(Sequence[str], policy["eligible_touch_types"]))
    assisted_floor = conversion_at - timedelta(days=cast(int, policy["assisted_days"]))
    last_floor = conversion_at - timedelta(days=cast(int, policy["last_click_days"]))
    eligible = [
        touch for touch in touches
        if touch["trace_link_id"] is not None
        and touch["touch_type"] in eligible_types
        and cast(datetime, touch["occurred_at"]) >= assisted_floor
    ]
    first = eligible[0] if eligible else None
    last_candidates = [
        touch
        for touch in eligible
        if cast(datetime, touch["occurred_at"]) >= last_floor
    ]
    last = last_candidates[-1] if last_candidates else None
    return {
        "revenue_id": str(revenue["revenue_id"]),
        "deal_id": str(revenue["deal_id"]),
        "conversion_id": str(revenue["conversion_id"]),
        "lead_id": str(revenue["lead_id"]),
        "session_id": str(revenue["session_id"]),
        "amount": float(cast(Decimal, revenue["amount"])),
        "currency": revenue["currency"],
        "direct": not eligible,
        "first_click": _touch_lineage(first),
        "last_click": _touch_lineage(last),
        "assisted": [_touch_lineage(touch) for touch in eligible],
        "unassigned": bool(eligible and last is None),
    }


def _touch_lineage(touch: Mapping[str, object] | None) -> dict[str, object] | None:
    if touch is None:
        return None
    return {
        "touch_id": str(touch["id"]),
        "occurred_at": cast(datetime, touch["occurred_at"]).isoformat(),
        "campaign_id": str(touch["campaign_id"]),
        "question_set_id": str(touch["question_set_id"]) if touch["question_set_id"] else None,
        "package_version_id": (
            str(touch["package_version_id"]) if touch["package_version_id"] else None
        ),
        "content_asset_key": touch["content_asset_key"],
        "verified_url": touch["verified_url"],
        "utm": touch["utm"],
    }


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = ["AttributionError", "AttributionService"]
