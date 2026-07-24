"""Durable Customer reader composition for Workflow C Report Snapshots."""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from geo_api.monitoring_runtime import _secret
from geo_core.workflow_c_reports import PostgresWorkflowCApprovedReportSnapshots


def build_workflow_c_customer_reader() -> PostgresWorkflowCApprovedReportSnapshots | None:
    """Return the PostgreSQL-only reader, never a memory fallback."""

    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None

    def connect():
        return psycopg.connect(database_url, row_factory=dict_row)

    return PostgresWorkflowCApprovedReportSnapshots(connect)


__all__ = ["build_workflow_c_customer_reader"]
