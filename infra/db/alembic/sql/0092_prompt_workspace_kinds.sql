ALTER TABLE prompt_programs
    DROP CONSTRAINT prompt_programs_program_kind_check;

ALTER TABLE prompt_programs
    ADD CONSTRAINT prompt_programs_program_kind_check CHECK (program_kind IN (
        'generation', 'claim_extraction', 'conflict_check', 'revision',
        'style_judge', 'arbiter', 'metric_judge', 'recommendation',
        'reference_translation', 'style_profile', 'offline_answer',
        'question_generation', 'rag_grounding', 'placement_generation',
        'placement_simulation'
    ));
