DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM prompt_program_test_run_tasks)
       OR EXISTS (SELECT 1 FROM prompt_program_command_receipts)
       OR EXISTS (SELECT 1 FROM prompt_program_bindings)
       OR EXISTS (SELECT 1 FROM prompt_program_test_evidence)
       OR EXISTS (SELECT 1 FROM prompt_program_release_states)
       OR EXISTS (SELECT 1 FROM prompt_program_releases)
       OR EXISTS (SELECT 1 FROM prompt_programs) THEN
        RAISE EXCEPTION 'cannot downgrade: Prompt Program data exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP TABLE prompt_program_command_receipts;
DROP TRIGGER prompt_program_bindings_immutable ON prompt_program_bindings;
DROP TRIGGER prompt_program_bindings_append_guard ON prompt_program_bindings;
DROP TABLE prompt_program_bindings;
DROP TRIGGER prompt_program_test_run_tasks_immutable ON prompt_program_test_run_tasks;
DROP TRIGGER prompt_program_test_run_tasks_insert_guard ON prompt_program_test_run_tasks;
DROP TABLE prompt_program_test_run_tasks;
DROP TRIGGER prompt_program_test_evidence_immutable ON prompt_program_test_evidence;
DROP TABLE prompt_program_test_evidence;
DROP TRIGGER prompt_program_release_states_immutable ON prompt_program_release_states;
DROP TRIGGER prompt_program_release_states_evidence_guard ON prompt_program_release_states;
DROP TRIGGER prompt_program_release_states_append_guard ON prompt_program_release_states;
DROP TABLE prompt_program_release_states;
DROP TRIGGER prompt_program_releases_immutable ON prompt_program_releases;
DROP TRIGGER prompt_program_releases_append_guard ON prompt_program_releases;
DROP TABLE prompt_program_releases;
DROP TRIGGER prompt_programs_immutable ON prompt_programs;
DROP TABLE prompt_programs;
DROP FUNCTION geo_assert_prompt_program_binding_append();
DROP FUNCTION geo_assert_prompt_program_test_run_task();
DROP FUNCTION geo_assert_prompt_program_state_evidence();
DROP FUNCTION geo_assert_prompt_program_state_append();
DROP FUNCTION geo_assert_prompt_program_release_append();
DROP FUNCTION geo_jsonb_canonical_text(jsonb);
