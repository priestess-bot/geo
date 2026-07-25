"""Errors shared by Workflow C semantic materialization components."""

from geo_core.workflow_c_analysis_common import WorkflowCAnalysisWorkerError


class WorkflowCSemanticMaterializationError(WorkflowCAnalysisWorkerError):
    """A frozen semantic manifest cannot be materialized under this lease."""


__all__ = ["WorkflowCSemanticMaterializationError"]
