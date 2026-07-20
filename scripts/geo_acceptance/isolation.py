"""Fail-closed PostgreSQL proof for inline acceptance isolation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import TracebackType
from typing import Literal, Mapping
from uuid import UUID

import psycopg

from scripts.geo_acceptance.contracts import AcceptanceConfig, run_scope_suffix


ConnectionKind = Literal["app", "worker", "admin"]


@dataclass(frozen=True)
class DatabaseProbe:
    kind: ConnectionKind
    endpoint_identity: tuple[str, int]
    database_name: str
    database_oid: int
    server_version_num: str
    principal: str
    isolation_marker: str | None
    configured_isolation_marker: str | None
    is_superuser: bool
    is_database_owner: bool
    is_app_member: bool
    is_worker_member: bool

    @property
    def database_identity(self) -> tuple[tuple[str, int], str, int, str]:
        return (
            self.endpoint_identity,
            self.database_name,
            self.database_oid,
            self.server_version_num,
        )


@dataclass(frozen=True)
class IsolationEvidence:
    sha256: str
    endpoint_sha256: str
    database_sha256: str
    principal_sha256: Mapping[str, str]
    isolation_marker: str

    def as_report(self) -> dict[str, object]:
        return {
            "sha256": self.sha256,
            "endpoint_sha256": self.endpoint_sha256,
            "database_sha256": self.database_sha256,
            "principal_sha256": dict(self.principal_sha256),
            "isolation_marker": self.isolation_marker,
        }


class InlineIsolationGuard:
    """Holds a run-scoped lock after proving a dedicated database contract."""

    def __init__(
        self,
        *,
        config: AcceptanceConfig,
        admin_connection: psycopg.Connection[tuple[object, ...]],
        evidence: IsolationEvidence,
        lock_key: int,
    ) -> None:
        self._config = config
        self._admin_connection = admin_connection
        self.evidence = evidence
        self._lock_key = lock_key
        self._released = False

    @classmethod
    def acquire(cls, config: AcceptanceConfig) -> InlineIsolationGuard:
        admin_connection = psycopg.connect(config.admin_database_url.strip(), autocommit=True)
        try:
            probes = {
                "admin": _probe_connection(admin_connection, "admin"),
                "app": _probe_url(config.app_database_url, "app"),
                "worker": _probe_url(config.worker_database_url, "worker"),
            }
            evidence = validate_database_probes(
                probes, expected_marker=config.isolation_marker.strip()
            )
            lock_key = _advisory_lock_key(config.run_id)
            locked = admin_connection.execute(
                "SELECT pg_try_advisory_lock(%s)", (lock_key,)
            ).fetchone()
            if locked is None or locked[0] is not True:
                raise RuntimeError("this acceptance run_id is already active")
            guard = cls(
                config=config,
                admin_connection=admin_connection,
                evidence=evidence,
                lock_key=lock_key,
            )
            guard._assert_scope_unused()
            return guard
        except BaseException:
            admin_connection.close()
            raise

    def __enter__(self) -> InlineIsolationGuard:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()

    def close(self) -> None:
        if self._released:
            return
        try:
            self._admin_connection.execute(
                "SELECT pg_advisory_unlock(%s)", (self._lock_key,)
            )
        finally:
            self._released = True
            self._admin_connection.close()

    def assert_created_scope(self, *, tenant_id: UUID, project_id: UUID) -> None:
        suffix = run_scope_suffix(self._config.run_id)
        row = self._admin_connection.execute(
            """SELECT t.name, p.name
               FROM tenants t JOIN projects p ON p.tenant_id = t.id
               WHERE t.id = %s AND p.id = %s""",
            (tenant_id, project_id),
        ).fetchone()
        expected = (
            f"GEO acceptance {suffix}",
            f"[SIMULATION] ADVINSYS acceptance {suffix}",
        )
        if row != expected:
            raise RuntimeError("acceptance tenant/project scope was not created as an isolated pair")

    def _assert_scope_unused(self) -> None:
        suffix = run_scope_suffix(self._config.run_id)
        row = self._admin_connection.execute(
            "SELECT EXISTS (SELECT 1 FROM tenants WHERE name = %s)",
            (f"GEO acceptance {suffix}",),
        ).fetchone()
        if row is None or row[0] is not False:
            raise RuntimeError("this acceptance run_id already has a persisted tenant scope")


def validate_database_probes(
    probes: Mapping[str, DatabaseProbe], *, expected_marker: str
) -> IsolationEvidence:
    if set(probes) != {"app", "worker", "admin"}:
        raise RuntimeError("app, worker and admin database probes are all required")
    app, worker, admin = probes["app"], probes["worker"], probes["admin"]
    if any(probe.kind != name for name, probe in probes.items()):
        raise RuntimeError("database probe identity does not match its configured purpose")
    if len({probe.database_identity for probe in probes.values()}) != 1:
        raise RuntimeError("app, worker and admin do not share one proven database endpoint")
    if any(probe.isolation_marker != expected_marker for probe in probes.values()):
        raise RuntimeError("database sessions do not inherit the expected isolation marker")
    if admin.configured_isolation_marker != expected_marker:
        raise RuntimeError("isolation marker is not configured at database scope")
    if any(
        probe.configured_isolation_marker not in {None, expected_marker}
        for probe in probes.values()
    ):
        raise RuntimeError("database isolation marker evidence is inconsistent")
    if len({probe.principal for probe in probes.values()}) != 3:
        raise RuntimeError("app, worker and admin must use distinct database principals")
    if not app.is_app_member or app.is_worker_member or app.is_superuser or app.is_database_owner:
        raise RuntimeError("app database principal does not have an isolated app-only identity")
    if not worker.is_worker_member or worker.is_app_member or worker.is_superuser or worker.is_database_owner:
        raise RuntimeError("worker database principal does not have an isolated worker-only identity")
    if not (admin.is_superuser or admin.is_database_owner):
        raise RuntimeError("admin database principal cannot prove database ownership")

    endpoint_payload = _canonical(app.endpoint_identity)
    database_payload = _canonical(app.database_identity)
    principal_hashes = {
        name: _sha256(probe.principal) for name, probe in sorted(probes.items())
    }
    fingerprint_payload = _canonical(
        {
            "endpoint": _sha256(endpoint_payload),
            "database": _sha256(database_payload),
            "principals": principal_hashes,
            "isolation_marker": expected_marker,
        }
    )
    return IsolationEvidence(
        sha256=_sha256(fingerprint_payload),
        endpoint_sha256=_sha256(endpoint_payload),
        database_sha256=_sha256(database_payload),
        principal_sha256=principal_hashes,
        isolation_marker=expected_marker,
    )


def _probe_url(url: str, kind: ConnectionKind) -> DatabaseProbe:
    with psycopg.connect(url.strip()) as connection:
        return _probe_connection(connection, kind)


def _probe_connection(
    connection: psycopg.Connection[tuple[object, ...]], kind: ConnectionKind
) -> DatabaseProbe:
    row = connection.execute(
        """SELECT current_database(), current_user, d.oid::bigint,
                  inet_server_addr()::text, inet_server_port(),
                  current_setting('server_version_num'),
                  current_setting('geo.acceptance_isolation_marker', true),
                  r.rolsuper, d.datdba = r.oid,
                  pg_has_role(current_user, 'geo_app', 'member'),
                  pg_has_role(current_user, 'geo_worker', 'member')
           FROM pg_database d JOIN pg_roles r ON r.rolname = current_user
           WHERE d.datname = current_database()"""
    ).fetchone()
    if row is None:
        raise RuntimeError(f"{kind} database identity could not be read")
    configured_marker: str | None = None
    if kind == "admin":
        marker_row = connection.execute(
            """SELECT split_part(setting, '=', 2)
               FROM pg_db_role_setting s
               CROSS JOIN LATERAL unnest(s.setconfig) AS setting
               WHERE s.setdatabase = %s AND s.setrole = 0
                 AND split_part(setting, '=', 1) = 'geo.acceptance_isolation_marker'""",
            (row[2],),
        ).fetchone()
        configured_marker = str(marker_row[0]) if marker_row is not None else None
    host = str(row[3] or connection.info.host or "local-socket")
    port = int(str(row[4] or connection.info.port or 0))
    return DatabaseProbe(
        kind=kind,
        endpoint_identity=(host, port),
        database_name=str(row[0]),
        database_oid=int(str(row[2])),
        server_version_num=str(row[5]),
        principal=str(row[1]),
        isolation_marker=str(row[6]) if row[6] else None,
        configured_isolation_marker=configured_marker,
        is_superuser=bool(row[7]),
        is_database_owner=bool(row[8]),
        is_app_member=bool(row[9]),
        is_worker_member=bool(row[10]),
    )


def _advisory_lock_key(run_id: str) -> int:
    return int.from_bytes(
        hashlib.sha256(f"geo-acceptance:{run_id}".encode()).digest()[:8],
        byteorder="big",
        signed=True,
    )


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
