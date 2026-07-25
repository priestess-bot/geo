"""Durable composition root for the complete Workflow C Internal API surface."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import cast

import psycopg
from psycopg.rows import dict_row

from geo_api.workflow_c_alert_postgres_control import PostgresWorkflowCAlertControl
from geo_api.workflow_c_alert_runtime import WorkflowCAlertRuntime
from geo_api.workflow_c_analysis_postgres_runtime import PostgresWorkflowCAnalysisRuntime
from geo_api.workflow_c_analysis_runtime import WorkflowCAnalysisPort
from geo_api.workflow_c_runtime import WorkflowCApi
from geo_api.workflow_c_sampling_postgres_runtime import (
    build_postgres_workflow_c_sampling_runtime,
)
from geo_api.workflow_c_sampling_runtime import WorkflowCSamplingRuntime
from geo_api.workflow_c_report_runtime import PostgresWorkflowCReportControl
from geo_core.alerts.postgres_lifecycle import PostgresWorkflowCAlertRepository
from geo_core.workflow_c_alert_admission import PostgresWorkflowCAlertAdmissionRepository
from geo_core.workflow_c_alert_rules import PostgresWorkflowCAlertRuleRepository
from geo_core.workflow_c_analysis_reads import PostgresWorkflowCAnalysisReadRepository
from geo_core.workflow_c_analysis_protocols import (
    PostgresWorkflowCMetricProtocolRepository,
)
from geo_core.workflow_c_artifacts import build_workflow_c_artifact_api_writer_composition
from geo_core.workflow_c_semantic_admission import (
    PostgresWorkflowCSemanticAdmissionRepository,
)
from geo_core.workflow_c_statistical_admission import (
    PostgresWorkflowCStatisticalAdmissionRepository,
)
from geo_core.workflow_c_statistical_protocols import (
    PostgresWorkflowCStatisticalProtocolRepository,
)
from geo_core.workflow_c_reports import PostgresWorkflowCApprovedReportSnapshots


def build_workflow_c_api(*, database_url: str) -> WorkflowCApi:
    """Mount only durable Workflow C adapters or fail Internal API readiness.

    Sampling commands use the existing project-scoped PostgreSQL controls and
    governed writer. Analysis reads immutable worker projections; its compute
    commands remain unavailable until their server-side input resolvers exist.
    Alert transitions use the fenced lifecycle repository. There is no memory
    fallback when any dependency, credential, canary or database permission is
    unavailable.
    """

    url = database_url.strip()
    if not url:
        raise ValueError("Workflow C database URL cannot be empty")
    keyring_path = os.getenv("GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE", "").strip()
    if not keyring_path:
        raise RuntimeError("GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE is required")

    def connect():
        return psycopg.connect(url, row_factory=dict_row)

    artifacts = build_workflow_c_artifact_api_writer_composition(
        connection_factory=connect,
        keyring_path=keyring_path,
    )
    return WorkflowCApi(
        sampling=cast(
            WorkflowCSamplingRuntime,
            build_postgres_workflow_c_sampling_runtime(
                connect=connect,
                artifact_writer=artifacts.writer,
            ),
        ),
        analysis=cast(
            WorkflowCAnalysisPort,
            PostgresWorkflowCAnalysisRuntime(
                reads=PostgresWorkflowCAnalysisReadRepository(connect=connect),
                protocols=PostgresWorkflowCMetricProtocolRepository(connect=connect),
                semantic_admission=PostgresWorkflowCSemanticAdmissionRepository(
                    connect=connect
                ),
                statistical_protocols=PostgresWorkflowCStatisticalProtocolRepository(
                    connect=connect
                ),
                statistical_admission=PostgresWorkflowCStatisticalAdmissionRepository(
                    connect=connect
                ),
            ),
        ),
        alerts=cast(
            WorkflowCAlertRuntime,
            PostgresWorkflowCAlertControl(
                repository=PostgresWorkflowCAlertRepository(connect=connect),
                rules=PostgresWorkflowCAlertRuleRepository(connect=connect),
                admission=PostgresWorkflowCAlertAdmissionRepository(connect=connect),
            ),
        ),
        reports=PostgresWorkflowCReportControl(
            repository=PostgresWorkflowCApprovedReportSnapshots(connect),
            clock=lambda: datetime.now(UTC),
        ),
        persistence="durable",
    )


__all__ = ["build_workflow_c_api"]
