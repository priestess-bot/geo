DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM prompt_programs
        WHERE program_kind IN (
            'question_generation', 'rag_grounding', 'placement_generation',
            'placement_simulation'
        )
    ) THEN
        RAISE EXCEPTION 'cannot downgrade: workspace flow Prompt Program data exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

ALTER TABLE prompt_programs
    DROP CONSTRAINT prompt_programs_program_kind_check;

ALTER TABLE prompt_programs
    ADD CONSTRAINT prompt_programs_program_kind_check CHECK (program_kind IN (
        'generation', 'claim_extraction', 'conflict_check', 'revision',
        'style_judge', 'arbiter', 'metric_judge', 'recommendation',
        'reference_translation', 'style_profile', 'offline_answer'
    ));
