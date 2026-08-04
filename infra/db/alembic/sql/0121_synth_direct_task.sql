ALTER TABLE synthetic_lab_execution_tasks
DROP CONSTRAINT synthetic_lab_execution_tasks_task_type_check;

ALTER TABLE synthetic_lab_execution_tasks
ADD CONSTRAINT synthetic_lab_execution_tasks_task_type_check CHECK (
    task_type IN (
        'geo_core.synthetic_lab.execution_contracts.StyleProfileBuildTask',
        'geo_core.synthetic_lab.execution_contracts.ReviewCaseRunTask',
        'geo_core.synthetic_lab.execution_contracts.DirectGenerationTask',
        'geo_core.synthetic_lab.execution_contracts.CorpusFinalizeTask',
        'geo_core.synthetic_lab.execution_contracts.OfflineExperimentRunTask'
    )
);

CREATE OR REPLACE FUNCTION geo_assert_synthetic_lab_execution_task() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE durable durable_jobs%ROWTYPE;
DECLARE metadata synthetic_lab_job_metadata%ROWTYPE;
DECLARE expected_kind text;
DECLARE expected_domain_kind text;
BEGIN
    SELECT * INTO STRICT durable FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT metadata FROM synthetic_lab_job_metadata
    WHERE job_id = NEW.job_id AND project_id = NEW.project_id;
    expected_kind := CASE NEW.task_type
        WHEN 'geo_core.synthetic_lab.execution_contracts.StyleProfileBuildTask'
            THEN 'style.profile.build'
        WHEN 'geo_core.synthetic_lab.execution_contracts.ReviewCaseRunTask'
            THEN 'review.case.run'
        WHEN 'geo_core.synthetic_lab.execution_contracts.DirectGenerationTask'
            THEN 'review.case.run'
        WHEN 'geo_core.synthetic_lab.execution_contracts.CorpusFinalizeTask'
            THEN 'corpus.finalize'
        WHEN 'geo_core.synthetic_lab.execution_contracts.OfflineExperimentRunTask'
            THEN 'offline_experiment.run'
    END;
    expected_domain_kind := CASE NEW.task_type
        WHEN 'geo_core.synthetic_lab.execution_contracts.StyleProfileBuildTask'
            THEN 'style_profile_build'
        WHEN 'geo_core.synthetic_lab.execution_contracts.ReviewCaseRunTask'
            THEN 'candidate_generation'
        WHEN 'geo_core.synthetic_lab.execution_contracts.DirectGenerationTask'
            THEN 'candidate_generation'
        WHEN 'geo_core.synthetic_lab.execution_contracts.CorpusFinalizeTask'
            THEN 'corpus_finalize'
        WHEN 'geo_core.synthetic_lab.execution_contracts.OfflineExperimentRunTask'
            THEN 'offline_experiment'
    END;
    IF NEW.execution_kind <> expected_kind OR durable.kind <> expected_kind
       OR metadata.domain_job_kind <> expected_domain_kind
       OR durable.input_hash <> NEW.expected_job_input_hash
       OR durable.status <> 'queued' THEN
        RAISE EXCEPTION 'Synthetic execution task does not match its queued Durable Job'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION geo_assert_synthetic_lab_execution_result() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE durable durable_jobs%ROWTYPE;
DECLARE metadata synthetic_lab_job_metadata%ROWTYPE;
DECLARE task synthetic_lab_execution_tasks%ROWTYPE;
DECLARE expected_result_type text;
BEGIN
    SELECT * INTO STRICT durable FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id FOR UPDATE;
    SELECT * INTO STRICT metadata FROM synthetic_lab_job_metadata
    WHERE job_id = NEW.job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT task FROM synthetic_lab_execution_tasks
    WHERE job_id = NEW.job_id AND project_id = NEW.project_id;
    expected_result_type := CASE task.task_type
        WHEN 'geo_core.synthetic_lab.execution_contracts.StyleProfileBuildTask'
            THEN 'geo_core.synthetic_lab.execution_contracts.StyleProfileBuildOutput'
        WHEN 'geo_core.synthetic_lab.execution_contracts.ReviewCaseRunTask'
            THEN 'geo_core.synthetic_lab.execution_contracts.ReviewCaseRunOutput'
        WHEN 'geo_core.synthetic_lab.execution_contracts.DirectGenerationTask'
            THEN 'geo_core.synthetic_lab.execution_contracts.ReviewCaseRunOutput'
        WHEN 'geo_core.synthetic_lab.execution_contracts.CorpusFinalizeTask'
            THEN 'geo_core.synthetic_lab.execution_contracts.CorpusFinalizeOutput'
        WHEN 'geo_core.synthetic_lab.execution_contracts.OfflineExperimentRunTask'
            THEN 'geo_core.synthetic_lab.execution_contracts.OfflineExperimentRunOutput'
    END;
    IF NEW.result_type <> expected_result_type
       OR durable.status NOT IN ('running', 'finalizing')
       OR durable.cancel_requested_at IS NOT NULL
       OR durable.lease_token IS DISTINCT FROM NEW.lease_token
       OR durable.fencing_generation <> NEW.fencing_generation
       OR durable.lease_expires_at IS NULL OR durable.lease_expires_at <= NEW.created_at
       OR (NEW.fact_snapshot_id, NEW.fact_snapshot_hash,
           NEW.profile_version_id, NEW.profile_hash,
           NEW.prompt_release_id, NEW.prompt_release_hash)
          IS DISTINCT FROM
          (metadata.fact_snapshot_id, metadata.fact_snapshot_hash,
           metadata.profile_version_id, metadata.profile_hash,
           metadata.prompt_release_id, metadata.prompt_release_hash) THEN
        RAISE EXCEPTION 'Synthetic execution result lost lease, fence, or frozen runtime lineage'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;
