DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM prompt_program_working_drafts AS draft
        JOIN prompt_program_releases AS release
          ON release.id = draft.base_release_id
         AND release.project_id = draft.project_id
        WHERE draft.revision > 1
           OR draft.candidate_release_id IS NOT NULL
           OR draft.system_template <> release.system_template
           OR draft.user_template <> release.user_template
    ) THEN
        RAISE EXCEPTION 'cannot downgrade: editable Prompt workspace data exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP TABLE prompt_program_working_drafts;

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
