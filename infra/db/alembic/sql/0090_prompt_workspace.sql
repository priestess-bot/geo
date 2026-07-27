CREATE TABLE prompt_program_working_drafts (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    program_id uuid NOT NULL,
    display_name text NOT NULL CHECK (btrim(display_name) <> ''),
    system_template text NOT NULL CHECK (btrim(system_template) <> ''),
    user_template text NOT NULL CHECK (btrim(user_template) <> ''),
    revision bigint NOT NULL CHECK (revision > 0),
    draft_hash text NOT NULL CHECK (draft_hash ~ '^[0-9a-f]{64}$'),
    base_release_id uuid NOT NULL,
    candidate_release_id uuid,
    updated_by uuid NOT NULL REFERENCES identities(id),
    updated_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, program_id),
    CONSTRAINT prompt_program_working_drafts_program_fkey FOREIGN KEY (
        program_id, project_id
    ) REFERENCES prompt_programs(id, project_id) ON DELETE CASCADE,
    CONSTRAINT prompt_program_working_drafts_base_fkey FOREIGN KEY (
        base_release_id, project_id
    ) REFERENCES prompt_program_releases(id, project_id),
    CONSTRAINT prompt_program_working_drafts_candidate_fkey FOREIGN KEY (
        candidate_release_id, project_id
    ) REFERENCES prompt_program_releases(id, project_id)
);

INSERT INTO prompt_program_working_drafts (
    project_id, program_id, display_name, system_template, user_template,
    revision, draft_hash, base_release_id, candidate_release_id,
    updated_by, updated_at
)
SELECT DISTINCT ON (program.id)
       program.project_id,
       program.id,
       CASE program.program_kind
           WHEN 'generation' THEN '候选测评生成'
           WHEN 'claim_extraction' THEN 'Claim 提取'
           WHEN 'conflict_check' THEN '知识冲突检查'
           WHEN 'revision' THEN '候选修订'
           WHEN 'style_judge' THEN '平台风格评审'
           WHEN 'arbiter' THEN '评审仲裁'
           WHEN 'metric_judge' THEN '语义指标评审'
           WHEN 'recommendation' THEN '建议生成'
           WHEN 'style_profile' THEN '风格画像生成'
           WHEN 'offline_answer' THEN '离线实验回答'
           ELSE program.purpose
       END,
       release.system_template,
       release.user_template,
       1,
       encode(digest(convert_to(geo_jsonb_canonical_text(jsonb_build_object(
           'display_name', CASE program.program_kind
               WHEN 'generation' THEN '候选测评生成'
               WHEN 'claim_extraction' THEN 'Claim 提取'
               WHEN 'conflict_check' THEN '知识冲突检查'
               WHEN 'revision' THEN '候选修订'
               WHEN 'style_judge' THEN '平台风格评审'
               WHEN 'arbiter' THEN '评审仲裁'
               WHEN 'metric_judge' THEN '语义指标评审'
               WHEN 'recommendation' THEN '建议生成'
               WHEN 'style_profile' THEN '风格画像生成'
               WHEN 'offline_answer' THEN '离线实验回答'
               ELSE program.purpose
           END,
           'system_template', release.system_template,
           'user_template', release.user_template
       )), 'UTF8'), 'sha256'), 'hex'),
       release.id,
       NULL,
       program.owner_id,
       release.created_at
FROM prompt_programs AS program
JOIN prompt_program_releases AS release
  ON release.project_id = program.project_id
 AND release.program_id = program.id
ORDER BY program.id, release.version DESC;

CREATE INDEX prompt_program_working_drafts_candidate_idx
ON prompt_program_working_drafts(project_id, candidate_release_id)
WHERE candidate_release_id IS NOT NULL;
CREATE INDEX prompt_program_working_drafts_updated_idx
ON prompt_program_working_drafts(project_id, updated_at DESC);
CREATE INDEX prompt_program_working_drafts_updated_by_idx
ON prompt_program_working_drafts(updated_by);

ALTER TABLE prompt_program_working_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE prompt_program_working_drafts FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON prompt_program_working_drafts
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE ALL ON prompt_program_working_drafts
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT, INSERT, UPDATE ON prompt_program_working_drafts TO geo_app;

-- Prompt publishing is now a single-operator product action. Test evidence remains
-- mandatory, but the same project operator may create and publish the Prompt.
CREATE OR REPLACE FUNCTION geo_assert_prompt_program_state_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    previous_status text;
    previous_version integer;
BEGIN
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
    RETURN NEW;
END;
$$;
