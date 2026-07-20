"""Append-only official report import persistence."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, cast
from uuid import UUID

from psycopg.types.json import Jsonb

from geo_core.monitoring.domain import MonitoringConflict
from geo_core.monitoring.official_reports import (
    OfficialReportImport,
    OfficialReportImportDraft,
    OfficialReportRow,
    OfficialReportRowDraft,
)
from geo_core.monitoring.source_contract import (
    ObservationPlatform,
    ObservationSurface,
    RawEvidence,
    RawEvidenceKind,
)


class MonitoringOfficialReportsMixin:
    """Composes with a repository that provides `_one`, `_optional` and `_many`."""

    _one: Any
    _optional: Any
    _many: Any

    def import_official_report(
        self,
        *,
        project_id: UUID,
        draft: OfficialReportImportDraft,
        rows: tuple[OfficialReportRowDraft, ...],
        actor_id: UUID,
        idempotency_key: str,
        payload_hash: str,
    ) -> OfficialReportImport:
        existing = self._optional(
            """SELECT * FROM monitoring_official_report_imports
               WHERE project_id = %s AND idempotency_key = %s""",
            (project_id, idempotency_key),
            "check the official report import idempotency key",
        )
        if existing is not None:
            return self._replayed_import(
                existing,
                campaign_id=draft.campaign_id,
                payload_hash=payload_hash,
            )

        artifact_uri = draft.artifact.artifact_uri
        artifact_hash = draft.artifact.artifact_hash
        if artifact_uri is None or artifact_hash is None:
            raise ValueError("official report import requires artifact evidence")
        imported = self._optional(
            """
            INSERT INTO monitoring_official_report_imports
              (project_id, campaign_id, capture_method, platform, platform_detail,
               surface, surface_kind, surface_detail, artifact_uri, artifact_hash,
               parser_name, parser_version, report_period_start, report_period_end,
               account_ref, row_count, contract_version, idempotency_key,
               payload_hash, imported_by)
            VALUES (%s, %s, 'official_report_import', %s, %s, %s,
                    'official_report', %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'geo-official-report-import-v1', %s, %s, %s)
            ON CONFLICT (project_id, idempotency_key) DO NOTHING
            RETURNING *
            """,
            (
                project_id,
                draft.campaign_id,
                draft.platform.value,
                draft.platform_detail,
                draft.surface.value,
                draft.surface_detail,
                artifact_uri,
                artifact_hash,
                draft.parser_name,
                draft.parser_version,
                draft.report_period_start,
                draft.report_period_end,
                draft.account_ref,
                len(rows),
                idempotency_key,
                payload_hash,
                actor_id,
            ),
            "persist the official report import",
        )
        if imported is None:
            concurrent = self._one(
                """SELECT * FROM monitoring_official_report_imports
                   WHERE project_id = %s AND idempotency_key = %s""",
                (project_id, idempotency_key),
                "read the concurrent official report import",
            )
            return self._replayed_import(
                concurrent,
                campaign_id=draft.campaign_id,
                payload_hash=payload_hash,
            )

        import_id = cast(UUID, imported["id"])
        for row in sorted(rows, key=lambda item: item.row_index):
            self._one(
                """
                INSERT INTO monitoring_official_report_rows
                  (project_id, campaign_id, import_id, capture_method, row_index,
                   row_data, eligible, ineligibility_reasons, row_hash)
                VALUES (%s, %s, %s, 'official_report_import', %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    project_id,
                    draft.campaign_id,
                    import_id,
                    row.row_index,
                    Jsonb(dict(row.row_data)),
                    row.eligible,
                    list(row.ineligible_reasons),
                    row.row_hash(),
                ),
                "persist an official report row",
            )
        return self._official_report_import(imported)

    def list_official_reports(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[OfficialReportImport, ...]:
        imports = self._many(
            """SELECT * FROM monitoring_official_report_imports
               WHERE project_id = %s AND campaign_id = %s
               ORDER BY imported_at DESC, id DESC""",
            (project_id, campaign_id),
            "list official report imports",
        )
        return tuple(self._official_report_import(row) for row in imports)

    def _replayed_import(
        self, row: Mapping[str, Any], *, campaign_id: UUID, payload_hash: str
    ) -> OfficialReportImport:
        if row["campaign_id"] != campaign_id or row["payload_hash"] != payload_hash:
            raise MonitoringConflict(
                "The idempotency key was already used for a different official report."
            )
        return self._official_report_import(row, replayed=True)

    def _official_report_import(
        self, row: Mapping[str, Any], *, replayed: bool = False
    ) -> OfficialReportImport:
        import_id = cast(UUID, row["id"])
        project_id = cast(UUID, row["project_id"])
        campaign_id = cast(UUID, row["campaign_id"])
        report_rows = self._many(
            """SELECT * FROM monitoring_official_report_rows
               WHERE project_id = %s AND campaign_id = %s AND import_id = %s
               ORDER BY row_index, id""",
            (project_id, campaign_id, import_id),
            "read official report rows",
        )
        artifact = RawEvidence(
            RawEvidenceKind.ARTIFACT,
            artifact_uri=str(row["artifact_uri"]),
            artifact_hash=str(row["artifact_hash"]),
            artifact_verified=True,
        )
        draft = OfficialReportImportDraft(
            campaign_id=campaign_id,
            platform=ObservationPlatform(str(row["platform"])),
            surface=ObservationSurface(str(row["surface"])),
            platform_detail=cast(str | None, row["platform_detail"]),
            surface_detail=cast(str | None, row["surface_detail"]),
            artifact=artifact,
            parser_name=str(row["parser_name"]),
            parser_version=str(row["parser_version"]),
            report_period_start=cast(date, row["report_period_start"]),
            report_period_end=cast(date, row["report_period_end"]),
            account_ref=str(row["account_ref"]),
        )
        return OfficialReportImport(
            id=import_id,
            project_id=project_id,
            draft=draft,
            payload_hash=str(row["payload_hash"]),
            imported_by=cast(UUID, row["imported_by"]),
            rows=tuple(_official_report_row(item) for item in report_rows),
            created_at=cast(datetime, row["imported_at"]),
            replayed=replayed,
        )


def _official_report_row(row: Mapping[str, Any]) -> OfficialReportRow:
    draft = OfficialReportRowDraft(
        row_index=int(row["row_index"]),
        row_data=cast(Mapping[str, object], row["row_data"]),
        eligible=bool(row["eligible"]),
        ineligible_reasons=tuple(row["ineligibility_reasons"] or ()),
    )
    return OfficialReportRow(
        id=cast(UUID, row["id"]),
        project_id=cast(UUID, row["project_id"]),
        import_id=cast(UUID, row["import_id"]),
        draft=draft,
        row_hash=str(row["row_hash"]),
        created_at=cast(datetime, row["created_at"]),
    )
