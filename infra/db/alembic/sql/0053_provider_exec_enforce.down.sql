DROP TRIGGER IF EXISTS workflow_c_sampling_attempt_verify_provider_execution_input
    ON workflow_c_sampling_attempts;
DROP FUNCTION IF EXISTS geo_verify_workflow_c_provider_execution_attempt();

DROP TRIGGER IF EXISTS workflow_c_sampling_suite_require_provider_execution_input
    ON workflow_c_sampling_suites;
DROP FUNCTION IF EXISTS geo_require_workflow_c_sampling_provider_execution_input();
