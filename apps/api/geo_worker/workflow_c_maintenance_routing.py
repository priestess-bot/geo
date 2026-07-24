"""Broker routing constants for the least-privilege Workflow C maintainer.

This module intentionally has no Dramatiq setup.  The relay and both Worker
modules can therefore share the routing identity without importing each
other's broker as a side effect.
"""

from __future__ import annotations

from geo_core.workflow_c_artifacts.lifecycle import (
    WORKFLOW_C_ARTIFACT_MAINTENANCE_JOB_KIND,
)


WORKFLOW_C_MAINTENANCE_QUEUE = "workflow-c-maintenance"
WORKFLOW_C_MAINTENANCE_ACTOR = "process_workflow_c_maintenance_job"
WORKFLOW_C_MAINTENANCE_OUTBOX_TOPICS = frozenset(
    {WORKFLOW_C_ARTIFACT_MAINTENANCE_JOB_KIND}
)


__all__ = [
    "WORKFLOW_C_ARTIFACT_MAINTENANCE_JOB_KIND",
    "WORKFLOW_C_MAINTENANCE_ACTOR",
    "WORKFLOW_C_MAINTENANCE_OUTBOX_TOPICS",
    "WORKFLOW_C_MAINTENANCE_QUEUE",
]
