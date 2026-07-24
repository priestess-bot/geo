from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.backup_envelope import BackupSecurityError
from scripts.write_restore_acl_rls_canary import validate_canary, write_canary


PROJECT_ID = str(uuid4())


def _evidence() -> str:
    return "\n".join(
        (
            "geo_restore_canary_app|f|f|f|f|f|t|t|t|f",
            "geo_restore_canary_worker|f|f|f|f|f|t|t|t|t",
            "geo_restore_canary_readonly|f|f|f|f|f|t|t|t|f",
        )
    ) + "\n"


def test_write_restore_acl_rls_canary_requires_non_owner_scoped_evidence(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence.txt"
    output = tmp_path / "receipt.json"
    evidence.write_text(_evidence(), encoding="ascii")

    receipt = write_canary(project_id=PROJECT_ID, evidence=evidence, output=output)

    assert receipt["rls_scoped_visibility_verified"] is True
    persisted = json.loads(output.read_text(encoding="ascii"))
    assert validate_canary(persisted) == persisted


@pytest.mark.parametrize(
    "line",
    (
        "geo_restore_canary_app|f|f|f|f|f|t|t|t|t",
        "geo_restore_canary_worker|f|f|f|t|f|t|t|t|t",
        "geo_restore_canary_readonly|f|f|f|f|f|t|t|f|f",
    ),
)
def test_restore_acl_rls_canary_rejects_privilege_or_scope_regression(
    tmp_path: Path, line: str
) -> None:
    evidence = tmp_path / "evidence.txt"
    lines = _evidence().splitlines()
    role = line.split("|", 1)[0]
    evidence.write_text(
        "\n".join(line if item.startswith(role + "|") else item for item in lines)
        + "\n",
        encoding="ascii",
    )

    with pytest.raises(BackupSecurityError):
        write_canary(project_id=PROJECT_ID, evidence=evidence, output=tmp_path / "out")
