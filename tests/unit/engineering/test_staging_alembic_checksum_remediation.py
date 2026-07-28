from __future__ import annotations

from contextlib import nullcontext
import json
from pathlib import Path
import stat
from typing import Any

import pytest

import scripts.remediate_staging_alembic_checksums as remediation
from scripts.remediate_staging_alembic_checksums import (
    BackupEvidence,
    ChecksumRemediationError,
    DatabaseIdentity,
    DatabaseSnapshot,
    DESTINATION_HASH_ALLOWLIST,
    HashPair,
    OLD_HASH_ALLOWLIST,
    REMEDIATED_REVISIONS,
    SourceState,
    TARGET_REVISION,
    TargetScope,
)


PROJECT_ID = "20000000-0000-4000-8000-000000000002"
SYSTEM_IDENTIFIER = "1234567890123456789"


def _canonical() -> dict[str, HashPair]:
    return {
        "0092_prompt_workspace_kinds": HashPair("a" * 64, "b" * 64),
        **DESTINATION_HASH_ALLOWLIST,
    }


def _target() -> TargetScope:
    return TargetScope(
        environment="staging",
        database_name="geo",
        database_user="geo_installer",
        system_identifier=SYSTEM_IDENTIFIER,
        project_ids=(PROJECT_ID,),
    )


def _schema() -> dict[str, object]:
    return {
        "columns": [],
        "constraints": [],
        "function_acl": [],
        "functions": [{"name": "guard", "definition": "RETURN NEW"}],
        "indexes": [],
        "policies": [{"name": "project_scope"}],
        "relation_acl": [{"grantee": "geo_worker", "privilege": "SELECT"}],
        "relations": [{"name": "dify_workflow_execution_results"}],
        "roles": [],
        "triggers": [{"name": "immutable", "definition": "BEFORE UPDATE"}],
        "upward_role_memberships": [],
    }


def _snapshot(*, canonical: bool = False) -> DatabaseSnapshot:
    ledger = _canonical()
    if not canonical:
        ledger.update(OLD_HASH_ALLOWLIST)
    return DatabaseSnapshot(
        identity=DatabaseIdentity(
            database_name="geo",
            database_user="geo_installer",
            system_identifier=SYSTEM_IDENTIFIER,
            project_ids=(PROJECT_ID,),
            fingerprint="9" * 64,
        ),
        heads=(TARGET_REVISION,),
        ledger=ledger,
        schema=_schema(),
    )


def _source() -> SourceState:
    files = (("one.sql", "1" * 64),)
    return SourceState(
        files=files,
        files_sha256=remediation._json_sha256(
            [{"path": "one.sql", "sha256": "1" * 64}]
        ),
        canonical_ledger_sha256=remediation._ledger_sha256(_canonical()),
    )


def _backup() -> BackupEvidence:
    ledger = _canonical()
    ledger.update(OLD_HASH_ALLOWLIST)
    return BackupEvidence(
        backup_id="backup-1",
        committed_sha256="2" * 64,
        manifest_sha256="3" * 64,
        restore_receipt_sha256="4" * 64,
        repository_ledger_sha256="5" * 64,
        database_ledger=ledger,
        database_ledger_sha256="6" * 64,
        scope=_target(),
    )


@pytest.fixture(autouse=True)
def _canonical_schema_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        remediation,
        "EXPECTED_SCHEMA_FINGERPRINT_SHA256",
        remediation._json_sha256(_schema()),
    )


def test_repository_destination_is_static_and_reviewed() -> None:
    canonical = remediation.repository_hashes()

    assert len(canonical) == 95
    assert tuple(canonical)[-1] == TARGET_REVISION
    assert {revision: canonical[revision] for revision in REMEDIATED_REVISIONS} == dict(
        DESTINATION_HASH_ALLOWLIST
    )
    assert all(
        DESTINATION_HASH_ALLOWLIST[revision] != OLD_HASH_ALLOWLIST[revision]
        for revision in REMEDIATED_REVISIONS
    )


def test_exact_out_of_band_target_and_allowlisted_snapshot_pass() -> None:
    remediation.validate_snapshot(
        _snapshot(), canonical=_canonical(), target=_target()
    )


@pytest.mark.parametrize(
    ("snapshot", "message"),
    [
        (
            DatabaseSnapshot(
                identity=_snapshot().identity,
                heads=("0094_dify_published_snapshot",),
                ledger=_snapshot().ledger,
                schema=_schema(),
            ),
            "single Alembic head",
        ),
        (
            DatabaseSnapshot(
                identity=_snapshot().identity,
                heads=(TARGET_REVISION,),
                ledger={**_snapshot().ledger, TARGET_REVISION: HashPair("0" * 64, "1" * 64)},
                schema=_schema(),
            ),
            "approved pre-repair",
        ),
        (
            DatabaseSnapshot(
                identity=DatabaseIdentity(
                    database_name="geo",
                    database_user="geo_installer",
                    system_identifier="999",
                    project_ids=(PROJECT_ID,),
                    fingerprint="8" * 64,
                ),
                heads=(TARGET_REVISION,),
                ledger=_snapshot().ledger,
                schema=_schema(),
            ),
            "out-of-band staging scope",
        ),
    ],
)
def test_preflight_rejects_wrong_head_hash_or_database_identity(
    snapshot: DatabaseSnapshot, message: str
) -> None:
    with pytest.raises(ChecksumRemediationError, match=message):
        remediation.validate_snapshot(snapshot, canonical=_canonical(), target=_target())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda schema: schema["policies"].append({"name": "public_read", "using": "true"}),
        lambda schema: schema["relation_acl"].append(
            {"grantee": "PUBLIC", "privilege": "SELECT"}
        ),
        lambda schema: schema["upward_role_memberships"].append(
            {"member": "geo_worker", "parent_role": "unsafe", "depth": 1}
        ),
        lambda schema: schema["functions"][0].update({"definition": "RETURN NULL"}),
        lambda schema: schema["triggers"][0].update({"enabled": "D"}),
        lambda schema: schema["relations"][0].update(
            {"view_definition": "SELECT secret FROM private"}
        ),
    ],
)
def test_complete_schema_fingerprint_rejects_policy_acl_membership_function_or_view_drift(
    mutate: Any,
) -> None:
    schema = json.loads(json.dumps(_schema()))
    mutate(schema)
    snapshot = DatabaseSnapshot(
        identity=_snapshot().identity,
        heads=(TARGET_REVISION,),
        ledger=_snapshot().ledger,
        schema=schema,
    )

    with pytest.raises(ChecksumRemediationError, match="schema fingerprint"):
        remediation.validate_snapshot(snapshot, canonical=_canonical(), target=_target())


class _Cursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class _UpdateConnection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.statement = ""
        self.parameters: list[str] = []

    def execute(self, statement: str, parameters: list[str]) -> _Cursor:
        self.statement = statement
        self.parameters = parameters
        return _Cursor(self.rows)


def test_apply_is_one_conditional_three_row_update() -> None:
    connection = _UpdateConnection([(revision,) for revision in REMEDIATED_REVISIONS])

    updated = remediation._apply_updates(connection, canonical=_canonical())  # type: ignore[arg-type]

    assert updated == 3
    assert "ledger.upgrade_sha256 = candidate.old_upgrade" in connection.statement
    assert "ledger.downgrade_sha256 = candidate.old_downgrade" in connection.statement
    assert "RETURNING ledger.revision" in connection.statement
    assert len(connection.parameters) == 15


def test_apply_rolls_back_if_returning_set_is_not_exact() -> None:
    connection = _UpdateConnection([(REMEDIATED_REVISIONS[0],)])
    with pytest.raises(ChecksumRemediationError, match="exactly the three"):
        remediation._apply_updates(connection, canonical=_canonical())  # type: ignore[arg-type]


class _TransactionConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def transaction(self) -> Any:
        return nullcontext()

    def execute(self, statement: str, parameters: object = None) -> _Cursor:
        del parameters
        self.statements.append(statement)
        return _Cursor([])


def test_dry_run_locks_all_contract_relations_and_never_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _TransactionConnection()
    monkeypatch.setattr(remediation, "_inspect_snapshot", lambda _connection: _snapshot())

    receipt = remediation.execute_remediation(
        connection,  # type: ignore[arg-type]
        canonical=_canonical(),
        source=_source(),
        backup=_backup(),
        target=_target(),
        apply=False,
        dry_run_receipt=None,
        allow_canonical_recovery=False,
    )

    assert receipt["mode"] == "dry_run"
    assert receipt["updated_rows"] == 0
    assert any("IN ACCESS EXCLUSIVE MODE" in value for value in connection.statements)
    assert not any(value.lstrip().startswith("UPDATE") for value in connection.statements)


def test_apply_is_bound_to_exact_dry_run_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _TransactionConnection()
    snapshots = iter((_snapshot(), _snapshot(canonical=True)))
    monkeypatch.setattr(
        remediation, "_inspect_snapshot", lambda _connection: next(snapshots)
    )
    monkeypatch.setattr(remediation, "_apply_updates", lambda *_args, **_kwargs: 3)
    dry = remediation._build_dry_run_receipt(
        frozen_plan={"different": True}, canonical=_canonical()
    )

    with pytest.raises(ChecksumRemediationError, match="does not match dry-run"):
        remediation.execute_remediation(
            connection,  # type: ignore[arg-type]
            canonical=_canonical(),
            source=_source(),
            backup=_backup(),
            target=_target(),
            apply=True,
            dry_run_receipt=dry,
            allow_canonical_recovery=False,
        )


def test_canonical_ledger_recovery_requires_preexisting_matching_pending_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _TransactionConnection()
    monkeypatch.setattr(
        remediation, "_inspect_snapshot", lambda _connection: _snapshot(canonical=True)
    )
    frozen = remediation._frozen_plan(
        _snapshot(), source=_source(), backup=_backup(), target=_target()
    )
    dry = remediation._build_dry_run_receipt(
        frozen_plan=frozen, canonical=_canonical()
    )

    with pytest.raises(ChecksumRemediationError, match="no matching pending"):
        remediation.execute_remediation(
            connection,  # type: ignore[arg-type]
            canonical=_canonical(),
            source=_source(),
            backup=_backup(),
            target=_target(),
            apply=True,
            dry_run_receipt=dry,
            allow_canonical_recovery=False,
        )

    recovered = remediation.execute_remediation(
        connection,  # type: ignore[arg-type]
        canonical=_canonical(),
        source=_source(),
        backup=_backup(),
        target=_target(),
        apply=True,
        dry_run_receipt=dry,
        allow_canonical_recovery=True,
    )
    assert recovered["recovered_after_unknown_commit"] is True
    assert recovered["updated_rows"] == 3


def test_pending_receipt_is_private_resumable_and_atomically_finalized(tmp_path: Path) -> None:
    path = tmp_path / "receipts" / "apply.json"
    intent = {"mode": "apply", "state": "pending", "nonce": "a" * 64}

    first = remediation.reserve_receipt(path, intent)
    assert first.resumed is False
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert remediation.reserve_receipt(path, intent).resumed is True
    with pytest.raises(ChecksumRemediationError, match="different or committed"):
        remediation.reserve_receipt(path, {**intent, "nonce": "b" * 64})

    committed = {"mode": "applied", "state": "committed", "receipt_sha256": "c" * 64}
    first.finalize(committed)
    assert json.loads(path.read_text(encoding="ascii")) == committed


def test_apply_pending_intent_is_stable_across_restarts() -> None:
    frozen = remediation._frozen_plan(
        _snapshot(), source=_source(), backup=_backup(), target=_target()
    )
    dry = remediation._build_dry_run_receipt(
        frozen_plan=frozen, canonical=_canonical()
    )

    first = remediation._pending_intent(
        apply=True,
        source=_source(),
        backup=_backup(),
        target=_target(),
        dry_run_receipt=dry,
    )
    second = remediation._pending_intent(
        apply=True,
        source=_source(),
        backup=_backup(),
        target=_target(),
        dry_run_receipt=dry,
    )

    assert first == second
    assert "created_at" not in first


def test_dry_run_receipt_freezes_plan_and_hides_raw_system_identifier(tmp_path: Path) -> None:
    frozen = remediation._frozen_plan(
        _snapshot(), source=_source(), backup=_backup(), target=_target()
    )
    receipt = remediation._build_dry_run_receipt(
        frozen_plan=frozen, canonical=_canonical()
    )
    path = tmp_path / "receipt.json"
    path.write_bytes(remediation.canonical_json(receipt) + b"\n")
    path.chmod(0o600)

    loaded = remediation._load_dry_run_receipt(path)
    encoded = json.dumps(loaded, sort_keys=True)
    assert SYSTEM_IDENTIFIER not in encoded
    assert loaded["receipt_sha256"] == remediation._json_sha256(
        {key: value for key, value in loaded.items() if key != "receipt_sha256"}
    )

    tampered = dict(loaded)
    tampered["canonical_ledger_sha256"] = "0" * 64
    path.write_bytes(remediation.canonical_json(tampered) + b"\n")
    with pytest.raises(ChecksumRemediationError, match="integrity"):
        remediation._load_dry_run_receipt(path)


def test_cli_requires_dry_receipt_only_for_apply() -> None:
    parser = remediation.build_parser()
    common = [
        "--database-url-file",
        "database-url",
        "--backup-dir",
        "backup",
        "--backup-keyring-file",
        "keyring",
        "--restore-receipt",
        "restore.json",
        "--receipt",
        "result.json",
        "--expected-environment",
        "staging",
        "--expected-database-name",
        "geo",
        "--expected-database-user",
        "geo_installer",
        "--expected-system-identifier",
        SYSTEM_IDENTIFIER,
        "--expected-project-id",
        PROJECT_ID,
    ]
    with pytest.raises(ChecksumRemediationError, match="dry-run-receipt"):
        remediation._validate_arguments(parser.parse_args([*common, "--apply"]))
    with pytest.raises(ChecksumRemediationError, match="only with --apply"):
        remediation._validate_arguments(
            parser.parse_args([*common, "--dry-run-receipt", "dry.json"])
        )


def test_arbitrary_backup_file_cannot_satisfy_authenticated_backup_gate(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    backup.mkdir(mode=0o700)
    fake = backup / "COMMITTED"
    fake.write_text("backup\n", encoding="ascii")
    fake.chmod(0o600)
    keyring = tmp_path / "keyring"
    keyring.write_text("not-a-keyring\n", encoding="ascii")
    keyring.chmod(0o600)
    restore = tmp_path / "restore.json"
    restore.write_text("{}\n", encoding="ascii")
    restore.chmod(0o600)

    with pytest.raises(ChecksumRemediationError, match="authenticated committed backup"):
        remediation.load_backup_evidence(
            backup_directory=backup,
            keyring_path=keyring,
            restore_receipt_path=restore,
            canonical=_canonical(),
            target=_target(),
        )
