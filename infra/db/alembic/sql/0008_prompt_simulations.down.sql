DROP TRIGGER IF EXISTS prompt_simulation_results_immutable ON prompt_simulation_results;
DROP TRIGGER IF EXISTS prompt_simulation_evidence_immutable ON prompt_simulation_evidence;
DROP TRIGGER IF EXISTS prompt_simulations_immutable ON prompt_simulations;
DROP TRIGGER IF EXISTS prompt_simulation_job_spec_kind ON prompt_simulation_job_specs;
DROP TRIGGER IF EXISTS prompt_simulation_scope_guard ON prompt_simulations;
DROP FUNCTION IF EXISTS geo_assert_prompt_simulation_scope();

DELETE FROM durable_jobs job
USING artifact_finalize_outbox artifact
WHERE job.id = artifact.job_id AND job.project_id = artifact.project_id
  AND artifact.resource_kind = 'prompt_simulation';

DROP TABLE IF EXISTS prompt_simulation_results;
DELETE FROM durable_jobs WHERE kind = 'prompt_simulation.generate';
DROP TABLE IF EXISTS prompt_simulation_job_specs;
DROP TABLE IF EXISTS prompt_simulation_evidence;
DROP TABLE IF EXISTS prompt_simulations;

ALTER TABLE artifact_finalize_outbox
    DROP CONSTRAINT artifact_finalize_outbox_resource_kind_check,
    ADD CONSTRAINT artifact_finalize_outbox_resource_kind_check
        CHECK (resource_kind IN ('prompt_bundle', 'package_export'));
