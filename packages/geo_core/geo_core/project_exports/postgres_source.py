"""Repeatable-read Monitoring source adapter for F027 exports."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from geo_core.monitoring.domain import MonitoringObservation, MonitoringProtocol
from geo_core.monitoring.postgres import PsycopgMonitoringRepository
from geo_core.project_exports.contracts import (
    AdminProjectExportInput,
    CustomerLatestApprovedProjectExportInput,
    ProjectExportData,
    ProjectExportRuleViolation,
    ProjectExportScope,
)
from geo_core.project_exports.monitoring_adapter import (
    citation_records,
    membership_record,
    metric_record,
    observation_record,
    protocol_record,
    query_record,
    report_record,
    source_stratum_record,
    verified_url_record,
)
from geo_core.project_scope import set_project_scope


class PostgresProjectExportSource:
    """Read one coherent public projection under project RLS."""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def load_admin(self, scope: ProjectExportScope) -> AdminProjectExportInput:
        connection = self._open(scope.project_id)
        try:
            repository = PsycopgMonitoringRepository(connection)
            data = self._load_admin_data(connection, repository, scope)
            connection.rollback()
            return AdminProjectExportInput(scope, data)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def load_customer_latest_approved(
        self, scope: ProjectExportScope
    ) -> CustomerLatestApprovedProjectExportInput:
        if scope.campaign_id is None:
            raise ProjectExportRuleViolation(
                "customer export requires an explicit campaign scope"
            )
        connection = self._open(scope.project_id)
        try:
            repository = PsycopgMonitoringRepository(connection)
            data = self._load_customer_data(repository, scope)
            connection.rollback()
            return CustomerLatestApprovedProjectExportInput(scope, data)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _open(self, project_id: UUID) -> Any:
        connection = self._connection_factory()
        connection.execute(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
        )
        set_project_scope(connection, project_id)
        connection.execute("SET LOCAL statement_timeout = '30s'")
        return connection

    def _load_admin_data(
        self,
        connection: Any,
        repository: PsycopgMonitoringRepository,
        scope: ProjectExportScope,
    ) -> ProjectExportData:
        campaign_ids = self._campaign_ids(connection, scope)
        protocols: list[MonitoringProtocol] = []
        observations: list[MonitoringObservation] = []
        snapshots: list[Any] = []
        reports: list[Any] = []
        urls: list[Any] = []
        queries: list[tuple[MonitoringProtocol, Any]] = []
        for campaign_id in campaign_ids:
            campaign_protocols = repository.list_protocols(
                project_id=scope.project_id, campaign_id=campaign_id
            )
            protocols.extend(campaign_protocols)
            for protocol in campaign_protocols:
                queries.extend(
                    (protocol, query)
                    for query in repository.list_protocol_queries(
                        project_id=scope.project_id,
                        campaign_id=campaign_id,
                        protocol_id=protocol.id,
                    )
                )
            observations.extend(
                repository.list_campaign_observations(
                    project_id=scope.project_id,
                    campaign_id=campaign_id,
                    protocol_id=None,
                    window=None,
                )
            )
            snapshots.extend(
                repository.list_metric_snapshots(
                    project_id=scope.project_id,
                    campaign_id=campaign_id,
                    latest_only=False,
                )
            )
            reports.extend(
                repository.list_reports(
                    project_id=scope.project_id,
                    campaign_id=campaign_id,
                    approved_only=True,
                )
            )
            urls.extend(
                repository.list_verified_urls(
                    project_id=scope.project_id, campaign_id=campaign_id
                )
            )
        memberships: list[Any] = []
        snapshots_by_campaign: dict[UUID, list[Any]] = {}
        for snapshot in snapshots:
            snapshots_by_campaign.setdefault(snapshot.campaign_id, []).append(snapshot)
        for campaign_id, values in snapshots_by_campaign.items():
            memberships.extend(
                repository.list_metric_observation_memberships(
                    project_id=scope.project_id,
                    campaign_id=campaign_id,
                    snapshot_ids=tuple(item.id for item in values),
                )
            )
        snapshot_by_id = {item.id: item for item in snapshots}
        return _export_data(
            scope.project_id,
            protocols=protocols,
            protocol_queries=queries,
            observations=observations,
            snapshots=snapshots,
            memberships=memberships,
            snapshot_by_id=snapshot_by_id,
            reports=reports,
            urls=urls,
        )

    def _load_customer_data(
        self,
        repository: PsycopgMonitoringRepository,
        scope: ProjectExportScope,
    ) -> ProjectExportData:
        campaign_id = scope.campaign_id
        assert campaign_id is not None
        approved = repository.list_customer_approved_report_snapshots(
            project_id=scope.project_id, campaign_id=campaign_id
        )
        snapshots = [item.snapshot for item in approved]
        snapshot_by_id = {item.id: item for item in snapshots}
        snapshot_ids = tuple(snapshot_by_id)
        memberships = repository.list_metric_observation_memberships(
            project_id=scope.project_id,
            campaign_id=campaign_id,
            snapshot_ids=snapshot_ids,
        )
        observations_by_snapshot = repository.list_metric_snapshot_observations(
            project_id=scope.project_id,
            campaign_id=campaign_id,
            snapshot_ids=snapshot_ids,
        )
        observations = {
            observation.id: observation
            for values in observations_by_snapshot.values()
            for observation in values
        }
        protocol_ids = {item.protocol_id for item in snapshots}
        protocols = [
            item
            for item in repository.list_protocols(
                project_id=scope.project_id, campaign_id=campaign_id
            )
            if item.id in protocol_ids
        ]
        protocol_queries = [
            (protocol, query)
            for protocol in protocols
            for query in repository.list_protocol_queries(
                project_id=scope.project_id,
                campaign_id=campaign_id,
                protocol_id=protocol.id,
            )
        ]
        urls = repository.list_customer_approved_verified_urls(
            project_id=scope.project_id, campaign_id=campaign_id
        )
        return _export_data(
            scope.project_id,
            protocols=protocols,
            protocol_queries=protocol_queries,
            observations=list(observations.values()),
            snapshots=snapshots,
            memberships=list(memberships),
            snapshot_by_id=snapshot_by_id,
            reports=[item.report for item in approved],
            urls=list(urls),
        )

    @staticmethod
    def _campaign_ids(connection: Any, scope: ProjectExportScope) -> tuple[UUID, ...]:
        rows = connection.execute(
            """SELECT id FROM geo_campaigns
               WHERE project_id = %s AND (%s::uuid IS NULL OR id = %s)
               ORDER BY id""",
            (scope.project_id, scope.campaign_id, scope.campaign_id),
        ).fetchall()
        result = tuple(row["id"] if isinstance(row, dict) else row[0] for row in rows)
        if scope.campaign_id is not None and result != (scope.campaign_id,):
            raise ProjectExportRuleViolation(
                "campaign scope does not belong to the requested project"
            )
        return result


def _export_data(
    project_id: UUID,
    *,
    protocols: list[Any],
    protocol_queries: list[tuple[Any, Any]],
    observations: list[Any],
    snapshots: list[Any],
    memberships: list[Any],
    snapshot_by_id: dict[UUID, Any],
    reports: list[Any],
    urls: list[Any],
) -> ProjectExportData:
    return ProjectExportData(
        protocols=tuple(protocol_record(item) for item in protocols),
        protocol_source_strata=tuple(
            source_stratum_record(protocol, source)
            for protocol in protocols
            for source in protocol.source_strata
        ),
        queries=tuple(
            query_record(protocol, query) for protocol, query in protocol_queries
        ),
        observations=tuple(observation_record(item) for item in observations),
        citations=tuple(
            citation
            for observation in observations
            for citation in citation_records(observation)
        ),
        metric_snapshots=tuple(metric_record(item) for item in snapshots),
        metric_observation_memberships=tuple(
            membership_record(snapshot_by_id[item.snapshot_id], item)
            for item in memberships
        ),
        approved_reports=tuple(report_record(item) for item in reports),
        verified_urls=tuple(verified_url_record(project_id, item) for item in urls),
    )
