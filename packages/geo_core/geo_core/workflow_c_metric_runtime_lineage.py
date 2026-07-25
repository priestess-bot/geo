"""Frozen model-runtime lineage checks for Workflow C metric children."""

from __future__ import annotations

from geo_core.model_gateway.runtime_execution import LoadedModelCallRuntime
from geo_core.workflow_c_metric_judge_worker_contracts import MetricChild


def metric_runtime_lineage_matches(
    runtime: LoadedModelCallRuntime, child: MetricChild
) -> bool:
    """Return whether every frozen admission field matches the metric child."""

    job = runtime.job
    return all(
        (
            job.runtime_manifest_id == child.runtime_manifest_id,
            job.runtime_manifest_hash == child.runtime_manifest_hash,
            job.runtime_option_id == child.runtime_option_id,
            job.runtime_option_hash == child.runtime_option_hash,
            job.runtime_option_id == child.runtime_selection_id,
            job.prompt_binding_id == child.prompt_binding_id,
            job.prompt_release_id == child.prompt_release_id,
            job.prompt_release_hash == child.prompt_release_hash,
            job.prompt_state_id == child.prompt_frozen_state_id,
            job.prompt_state_version == child.prompt_state_version,
            job.prompt_bundle_hash == child.prompt_bundle_hash,
            job.output_schema_hash == child.portable_output_schema_hash,
            job.application_output_schema_hash == child.application_output_schema_hash,
            job.purpose == child.prompt_purpose,
        )
    )


__all__ = ["metric_runtime_lineage_matches"]
