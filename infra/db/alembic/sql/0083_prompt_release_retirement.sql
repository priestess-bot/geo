ALTER TABLE prompt_program_release_states
DROP CONSTRAINT prompt_program_release_states_status_check;
ALTER TABLE prompt_program_release_states
ADD CONSTRAINT prompt_program_release_states_status_check
CHECK (status IN ('draft', 'tested', 'approved', 'frozen', 'retired'));

ALTER TABLE prompt_program_command_receipts
DROP CONSTRAINT prompt_program_command_receipts_operation_check;
ALTER TABLE prompt_program_command_receipts
ADD CONSTRAINT prompt_program_command_receipts_operation_check
CHECK (operation IN (
    'create', 'create_release', 'test', 'approve', 'freeze', 'retire', 'bind', 'diff'
));

ALTER TABLE prompt_program_command_receipts
DROP CONSTRAINT prompt_program_command_receipts_result_shape;
ALTER TABLE prompt_program_command_receipts
ADD CONSTRAINT prompt_program_command_receipts_result_shape CHECK (
    (operation = 'create' AND result_kind = 'created')
    OR (operation = 'create_release' AND result_kind = 'created_release')
    OR (operation = 'test' AND result_kind = 'tested')
    OR (operation IN ('approve', 'freeze', 'retire') AND result_kind = 'transitioned')
    OR (operation = 'bind' AND result_kind = 'bound')
    OR (operation = 'diff' AND result_kind = 'diffed')
);

CREATE OR REPLACE FUNCTION geo_assert_prompt_program_state_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    previous_status text;
    previous_version integer;
    release_owner uuid;
BEGIN
    SELECT owner_id INTO STRICT release_owner
    FROM prompt_program_releases
    WHERE id = NEW.release_id
      AND project_id = NEW.project_id
      AND release_hash = NEW.release_hash;

    IF NEW.version = 1 THEN
        IF NEW.previous_state_id IS NOT NULL OR NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'Prompt Program initial state must be draft'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    SELECT status, version INTO STRICT previous_status, previous_version
    FROM prompt_program_release_states
    WHERE id = NEW.previous_state_id
      AND project_id = NEW.project_id
      AND release_id = NEW.release_id
      AND release_hash = NEW.release_hash;

    IF NEW.version <> previous_version + 1
       OR NOT (
           (previous_status = 'draft' AND NEW.status = 'tested')
           OR (previous_status = 'tested' AND NEW.status = 'approved')
           OR (previous_status = 'approved' AND NEW.status = 'frozen')
           OR (previous_status = 'frozen' AND NEW.status = 'retired')
       ) THEN
        RAISE EXCEPTION 'Prompt Program state transition is not linear'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'approved' AND NEW.acted_by = release_owner THEN
        RAISE EXCEPTION 'Prompt Program owner cannot approve own Release'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION geo_assert_prompt_program_state_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    previous record;
    evidence record;
    release_record record;
BEGIN
    IF NEW.status = 'draft' THEN
        RETURN NULL;
    END IF;
    IF NEW.status = 'tested' THEN
        SELECT * INTO STRICT release_record
        FROM prompt_program_releases
        WHERE id = NEW.release_id
          AND project_id = NEW.project_id
          AND release_hash = NEW.release_hash;
        SELECT * INTO STRICT evidence
        FROM prompt_program_test_evidence
        WHERE project_id = NEW.project_id
          AND release_id = NEW.release_id
          AND release_hash = NEW.release_hash
          AND tested_state_id = NEW.id;
        IF NEW.evidence_ref <> 'prompt-test:' || evidence.id || ':' || evidence.evidence_hash
           OR evidence.tested_by IS DISTINCT FROM NEW.acted_by
           OR evidence.tested_at IS DISTINCT FROM NEW.acted_at
           OR evidence.test_set_id IS DISTINCT FROM release_record.test_set_id
           OR evidence.test_set_version IS DISTINCT FROM release_record.test_set_version THEN
            RAISE EXCEPTION 'Prompt Program tested state evidence is inconsistent'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;

    SELECT * INTO STRICT previous
    FROM prompt_program_release_states
    WHERE id = NEW.previous_state_id
      AND project_id = NEW.project_id
      AND release_id = NEW.release_id
      AND release_hash = NEW.release_hash;
    IF NEW.status = 'approved' THEN
        SELECT * INTO STRICT release_record
        FROM prompt_program_releases
        WHERE id = previous.release_id
          AND project_id = previous.project_id
          AND release_hash = previous.release_hash;
        SELECT * INTO STRICT evidence
        FROM prompt_program_test_evidence
        WHERE project_id = previous.project_id
          AND release_id = previous.release_id
          AND release_hash = previous.release_hash
          AND tested_state_id = previous.id;
        IF previous.evidence_ref <> 'prompt-test:' || evidence.id || ':' || evidence.evidence_hash
           OR NEW.evidence_ref <> 'approval:' || evidence.id || ':' || evidence.evidence_hash
           OR evidence.tested_by IS DISTINCT FROM previous.acted_by
           OR evidence.tested_at IS DISTINCT FROM previous.acted_at
           OR evidence.test_set_id IS DISTINCT FROM release_record.test_set_id
           OR evidence.test_set_version IS DISTINCT FROM release_record.test_set_version THEN
            RAISE EXCEPTION 'Prompt Program approval evidence is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.status = 'frozen'
       AND NEW.evidence_ref <> 'freeze:' || previous.id || ':' || previous.release_hash THEN
        RAISE EXCEPTION 'Prompt Program freeze evidence is inconsistent'
            USING ERRCODE = '23514';
    ELSIF NEW.status = 'retired'
       AND NEW.evidence_ref <> 'retire:' || previous.id || ':' || previous.release_hash THEN
        RAISE EXCEPTION 'Prompt Program retirement evidence is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
