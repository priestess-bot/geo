-- The Worker creates one admission only while executing a claimed Durable Job.
-- geo_assert_model_gateway_job_admission_insert validates Job ownership, the
-- frozen runtime option and Prompt release, active Secret handle, and budget.
GRANT INSERT ON model_gateway_job_admissions TO geo_worker;
