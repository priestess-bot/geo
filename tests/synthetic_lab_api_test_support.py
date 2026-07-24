"""Request fixture builders shared by Synthetic Lab API contract tests."""

from __future__ import annotations

import base64
import hashlib
from uuid import UUID, uuid4


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def source_payload() -> dict[str, object]:
    return {
        "expected_version": 0,
        "channel": "reddit",
        "access_mode": "public",
        "locale": "en-AU",
        "source_url": "https://www.reddit.com/r/australia/",
        "source_label": None,
    }


def manual_source_payload() -> dict[str, object]:
    return {
        "expected_version": 0,
        "channel": "reddit",
        "access_mode": "manual_import",
        "locale": "en-AU",
        "source_url": None,
        "source_label": "Approved Reddit export",
    }


def import_payload(style_source_revision_id: UUID | str | None = None) -> dict[str, object]:
    content = "G'day, this pressure washer worked well in my Sydney courtyard."
    return {
        "expected_version": 0,
        "style_source_revision_id": str(style_source_revision_id or uuid4()),
        "import_format": "text",
        "filename": "reddit-sample.txt",
        "content_base64": base64.b64encode(content.encode()).decode("ascii"),
        "default_source_rights": "authorized_manual_capture",
        "rights_evidence_reference": "internal-rights-register:reddit-export-2026-07",
    }


def case_payload() -> dict[str, object]:
    return {
        "expected_version": 0,
        "case_key": "reddit-case-1",
        "ordinal": 1,
        "mode": "autonomous_scenario",
        "channel": "reddit",
        "persona": "Australian home owner",
        "use_case": "Compare two pressure washers",
        "subject": "Acme PW-20",
        "question_set_version_id": str(uuid4()),
        "fact_snapshot_id": str(uuid4()),
        "profile_version_id": str(uuid4()),
        "competitor_scenario": True,
        "expected_risks": ["subject_mix"],
    }


def job_payload() -> dict[str, object]:
    return {
        "expected_version": 0,
        "job_id": str(uuid4()),
        "outbox_id": str(uuid4()),
        "resource_id": str(uuid4()),
        "resource_hash": _hash(str(uuid4())),
        "runtime_inputs": {
            "fact_snapshot_id": str(uuid4()),
            "fact_snapshot_hash": _hash("facts"),
            "profile_version_id": str(uuid4()),
            "profile_hash": _hash("profile"),
            "prompt_release_id": str(uuid4()),
            "prompt_release_hash": _hash("prompt"),
        },
    }
