from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from geo_core.attribution import AttributionError, AttributionService
from geo_core.connectors.external_data import ExternalDataService

from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="PostgreSQL admin URL is not configured"),
]


def test_consent_trace_business_lineage_and_deterministic_snapshot() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_attr_{suffix}"
    target_url = _database_url(ADMIN_URL, database_name)
    app_login, password = f"geo_attr_{suffix}", uuid4().hex
    database_created = role_created = False
    migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    migration.attributes["geo_database_url_override"] = target_url
    now = datetime(2026, 7, 28, 5, 0, tzinfo=UTC)
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        database_created = True
        command.upgrade(migration, "head")
        with psycopg.connect(target_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(password)
                )
            )
            role_created = True
            seeded = seed_project(admin, suffix=f"attr-{suffix}")
            campaign_id = uuid4()
            admin.execute(
                """INSERT INTO geo_campaigns(
                       id, project_id, market_profile_id, primary_product_entity_id,
                       name, created_by
                   ) VALUES (%s, %s, %s, %s, 'Attribution evidence', %s)""",
                (
                    campaign_id, seeded["project"], seeded["market"],
                    seeded["entity"], seeded["owner"],
                ),
            )

        app_url = login_url(target_url, user=app_login, password=password)

        def connect():
            return psycopg.connect(app_url, row_factory=dict_row)

        service = AttributionService(connect=connect, clock=lambda: now)
        policy = service.create_policy(
            project_id=seeded["project"], actor_id=seeded["owner"]
        )
        collector = service.create_collector(
            project_id=seeded["project"],
            actor_id=seeded["owner"],
            name="Owned site",
            allowed_origins=["https://example.com"],
        )
        trace = service.issue_trace(
            project_id=seeded["project"],
            actor_id=seeded["owner"],
            campaign_id=campaign_id,
            content_asset_key="article:au-buyers-guide-v1",
            verified_url="https://example.com/au/buyers-guide",
        )
        session_key = uuid4()
        with pytest.raises(AttributionError, match="consent"):
            service.collect(
                project_id=seeded["project"], collector_id=collector["id"],
                write_key=collector["write_key"], origin="https://example.com",
                client_session_id=session_key, source_event_id="session-denied",
                event_type="session_start", occurred_at=now - timedelta(days=89),
                consent=False, consent_schema_version="consent-v1",
                trace_token=None, utm={},
            )
        session = service.collect(
            project_id=seeded["project"], collector_id=collector["id"],
            write_key=collector["write_key"], origin="https://example.com",
            client_session_id=session_key, source_event_id="session-1",
            event_type="session_start", occurred_at=now - timedelta(days=89),
            consent=True, consent_schema_version="consent-v1", trace_token=None, utm={},
        )
        first = service.collect(
            project_id=seeded["project"], collector_id=collector["id"],
            write_key=collector["write_key"], origin="https://example.com",
            client_session_id=session_key, source_event_id="touch-first",
            event_type="page_view", occurred_at=now - timedelta(days=89),
            consent=True, consent_schema_version="consent-v1",
            trace_token=trace["trace_token"], utm={"source": "geo", "campaign": "au"},
        )
        last = service.collect(
            project_id=seeded["project"], collector_id=collector["id"],
            write_key=collector["write_key"], origin="https://example.com/",
            client_session_id=session_key, source_event_id="touch-last",
            event_type="click", occurred_at=now - timedelta(days=29),
            consent=True, consent_schema_version="consent-v1",
            trace_token=trace["trace_token"], utm={"source": "geo", "campaign": "au"},
        )
        replay = service.collect(
            project_id=seeded["project"], collector_id=collector["id"],
            write_key=collector["write_key"], origin="https://example.com",
            client_session_id=session_key, source_event_id="touch-last",
            event_type="click", occurred_at=now - timedelta(days=29),
            consent=True, consent_schema_version="consent-v1",
            trace_token=trace["trace_token"], utm={"source": "geo", "campaign": "au"},
        )
        assert replay["touch_id"] == last["touch_id"] and replay["replayed"] is True

        lead = service.record_business_event(
            project_id=seeded["project"], kind="lead", source_event_id="lead-1",
            parent_id=session["session_id"], occurred_at=now - timedelta(days=2),
            local_business_id="lead-local-1",
        )
        conversion = service.record_business_event(
            project_id=seeded["project"], kind="conversion",
            source_event_id="conversion-1", parent_id=lead["id"],
            occurred_at=now - timedelta(days=1), label="qualified_lead",
        )
        deal = service.record_business_event(
            project_id=seeded["project"], kind="deal", source_event_id="deal-1",
            parent_id=conversion["id"], occurred_at=now - timedelta(hours=2),
            local_business_id="deal-local-1", currency="AUD", amount=Decimal("1250.00"),
        )
        revenue = service.record_business_event(
            project_id=seeded["project"], kind="revenue", source_event_id="revenue-1",
            parent_id=deal["id"], occurred_at=now - timedelta(hours=1), label="booked",
            currency="AUD", amount=Decimal("1250.00"),
        )
        assert revenue["replayed"] is False
        direct_session = service.collect(
            project_id=seeded["project"], collector_id=collector["id"],
            write_key=collector["write_key"], origin="https://example.com",
            client_session_id=uuid4(), source_event_id="direct-session",
            event_type="direct", occurred_at=now - timedelta(days=1),
            consent=True, consent_schema_version="consent-v1", trace_token=None, utm={},
        )
        direct_lead = service.record_business_event(
            project_id=seeded["project"], kind="lead", source_event_id="direct-lead",
            parent_id=direct_session["session_id"], occurred_at=now - timedelta(hours=20),
            local_business_id="direct-lead-local",
        )
        direct_conversion = service.record_business_event(
            project_id=seeded["project"], kind="conversion",
            source_event_id="direct-conversion", parent_id=direct_lead["id"],
            occurred_at=now - timedelta(hours=10), label="qualified_lead",
        )
        direct_deal = service.record_business_event(
            project_id=seeded["project"], kind="deal", source_event_id="direct-deal",
            parent_id=direct_conversion["id"], occurred_at=now - timedelta(hours=8),
            local_business_id="direct-deal-local", currency="AUD", amount=Decimal("50"),
        )
        service.record_business_event(
            project_id=seeded["project"], kind="revenue", source_event_id="direct-revenue",
            parent_id=direct_deal["id"], occurred_at=now - timedelta(hours=7),
            label="booked", currency="AUD", amount=Decimal("50"),
        )
        imported_lead, imported_conversion, imported_deal, imported_revenue = (
            uuid4() for _ in range(4)
        )
        import_rows = [
            {
                "id": imported_lead, "kind": "lead", "source_event_id": "import-lead-1",
                "parent_id": session["session_id"], "occurred_at": now - timedelta(minutes=50),
                "local_business_id": "imported-lead-local-1",
            },
            {
                "id": imported_conversion, "kind": "conversion",
                "source_event_id": "import-conversion-1", "parent_id": imported_lead,
                "occurred_at": now - timedelta(minutes=40), "label": "qualified_lead",
            },
            {
                "id": imported_deal, "kind": "deal", "source_event_id": "import-deal-1",
                "parent_id": imported_conversion, "occurred_at": now - timedelta(minutes=30),
                "local_business_id": "imported-deal-local-1", "currency": "AUD",
                "amount": Decimal("400.00"),
            },
            {
                "id": imported_revenue, "kind": "revenue",
                "source_event_id": "import-revenue-1", "parent_id": imported_deal,
                "occurred_at": now - timedelta(minutes=20), "label": "booked",
                "currency": "AUD", "amount": Decimal("400.00"),
            },
            {
                "id": uuid4(), "kind": "revenue", "source_event_id": "import-invalid-1",
                "parent_id": uuid4(), "occurred_at": now - timedelta(minutes=10),
                "label": "booked", "currency": "AUD", "amount": Decimal("1.00"),
            },
        ]
        imported = service.import_business_rows(
            project_id=seeded["project"], actor_id=seeded["owner"],
            template_schema_version="attribution-business-import-v1", rows=import_rows,
        )
        imported_replay = service.import_business_rows(
            project_id=seeded["project"], actor_id=seeded["owner"],
            template_schema_version="attribution-business-import-v1", rows=import_rows,
        )
        assert imported["accepted_count"] == 4 and imported["rejected_count"] == 1
        assert imported["result"]["rejected"][0]["code"] == "invalid_row"
        assert imported_replay["id"] == imported["id"] and imported_replay["replayed"] is True
        snapshot = service.create_snapshot(
            project_id=seeded["project"], actor_id=seeded["owner"],
            cutoff_at=now, policy_id=policy["id"],
        )
        replayed_snapshot = service.create_snapshot(
            project_id=seeded["project"], actor_id=seeded["owner"],
            cutoff_at=now, policy_id=policy["id"],
        )
        entry = next(
            item for item in snapshot["result"]["entries"]
            if item["revenue_id"] == str(revenue["id"])
        )
        assert snapshot["result"]["methodology"] == "observational_association_not_causation"
        assert entry["first_click"]["touch_id"] == str(first["touch_id"])
        assert entry["last_click"]["touch_id"] == str(last["touch_id"])
        assert len(entry["assisted"]) == 2 and entry["direct"] is False
        assert entry["last_click"]["content_asset_key"] == "article:au-buyers-guide-v1"
        assert len(snapshot["result"]["entries"]) == 3
        direct_entry = next(
            item for item in snapshot["result"]["entries"] if item["direct"]
        )
        assert direct_entry["first_click"] is None
        assert direct_entry["last_click"] is None
        assert direct_entry["assisted"] == []
        assert replayed_snapshot["id"] == snapshot["id"]
        assert replayed_snapshot["replayed"] is True
        external = ExternalDataService(connect=connect, clock=lambda: now)
        report = external.create_attribution_report(
            project_id=seeded["project"], campaign_id=campaign_id,
            attribution_snapshot_id=snapshot["id"], actor_id=seeded["owner"],
            title="GEO content attribution", summary="Campaign-level approved aggregate",
        )
        assert external.submit(
            project_id=seeded["project"], report_id=report["id"]
        )["status"] == "in_review"
        approved_report = external.decide(
            project_id=seeded["project"], report_id=report["id"],
            snapshot_hash=report["snapshot"]["snapshot_hash"], decision="approved",
            actor_id=seeded["reviewer"], reason="Campaign attribution reviewed",
            review_evidence={"methodology": "observational"},
            idempotency_key=f"approve-attribution:{report['id']}",
        )
        assert approved_report["status"] == "approved"
        customer = external.latest(project_id=seeded["project"], campaign_id=campaign_id)
        attribution_payload = customer[0]["customer_payload"]
        assert customer[0]["source_kind"] == "attribution_snapshot"
        assert attribution_payload["summary"]["revenue_count"] == 2
        assert attribution_payload["summary"]["revenue_by_currency"] == {"AUD": 1650.0}
        assert "entries" not in attribution_payload
        assert "lead_id" not in str(attribution_payload)
        inventory = service.inventory(project_id=seeded["project"])
        assert inventory["policies"][0]["id"] == policy["id"]
        assert inventory["collectors"][0]["id"] == collector["id"]
        assert "write_key_hash" not in inventory["collectors"][0]
        assert inventory["counts"] == {
            "traces": 1,
            "sessions": 2,
            "touches": 3,
            "leads": 3,
            "conversions": 3,
            "deals": 3,
            "revenues": 3,
        }
        assert inventory["snapshots"][0]["result_hash"] == snapshot["result_hash"]
    finally:
        if role_created:
            with psycopg.connect(target_url, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))
        if database_created:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                    (database_name,),
                )
                server.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


def _database_url(admin_url: str, database_name: str) -> str:
    parsed = urlparse(admin_url)
    return urlunparse(parsed._replace(path=f"/{database_name}"))
