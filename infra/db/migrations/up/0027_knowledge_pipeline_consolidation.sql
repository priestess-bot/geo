-- Consolidate the production knowledge path around active approved facts and
-- versioned generation templates. The migration is idempotent for local resets.

UPDATE localized_knowledge_facts
SET status = 'active'
WHERE status = 'approved';

ALTER TABLE localized_knowledge_facts
  DROP CONSTRAINT IF EXISTS localized_knowledge_facts_status_check;
ALTER TABLE localized_knowledge_facts
  ADD CONSTRAINT localized_knowledge_facts_status_check
  CHECK (status IN ('active', 'superseded', 'archived', 'forbidden'));

ALTER TABLE crawl_jobs
  ADD COLUMN IF NOT EXISTS seed_urls text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS include_patterns text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS exclude_patterns text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS respect_robots boolean NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS crawled_page_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS failed_page_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

INSERT INTO prompt_generation_templates (
  template_key, template_version, name, template_body, status, metadata, created_by
)
VALUES
  (
	    'brand_visibility_prompt_v1', 'v1', '品牌可见性',
	    'Generate customer questions that reveal whether the target brand is mentioned and recommended. Use only approved facts and preserve source trace references.',
	    CASE WHEN EXISTS (
	      SELECT 1 FROM pg_constraint
	      WHERE conname = 'prompt_generation_templates_status_check'
	        AND pg_get_constraintdef(oid) LIKE '%published%'
	    ) THEN 'published' ELSE 'active' END,
	    '{"intent_type":"brand_visibility","built_in":true}'::jsonb, 'system'
  ),
  (
    'competitor_comparison_prompt_v1', 'v1', '竞品比较',
    'Generate balanced comparison questions using approved brand and competitor facts. Do not introduce unsupported claims.',
	    CASE WHEN EXISTS (
	      SELECT 1 FROM pg_constraint
	      WHERE conname = 'prompt_generation_templates_status_check'
	        AND pg_get_constraintdef(oid) LIKE '%published%'
	    ) THEN 'published' ELSE 'active' END,
	    '{"intent_type":"competitor_comparison","built_in":true}'::jsonb, 'system'
  ),
  (
    'faq_purchase_decision_prompt_v1', 'v1', '购买决策 FAQ',
    'Generate purchase-decision questions grounded in approved product, policy, service and market facts.',
	    CASE WHEN EXISTS (
	      SELECT 1 FROM pg_constraint
	      WHERE conname = 'prompt_generation_templates_status_check'
	        AND pg_get_constraintdef(oid) LIKE '%published%'
	    ) THEN 'published' ELSE 'active' END,
	    '{"intent_type":"purchase_decision","built_in":true}'::jsonb, 'system'
  ),
  (
    'local_city_intent_prompt_v1', 'v1', '本地城市意图',
    'Generate locally relevant questions for the configured city and market using only approved localized facts.',
	    CASE WHEN EXISTS (
	      SELECT 1 FROM pg_constraint
	      WHERE conname = 'prompt_generation_templates_status_check'
	        AND pg_get_constraintdef(oid) LIKE '%published%'
	    ) THEN 'published' ELSE 'active' END,
	    '{"intent_type":"local_city","built_in":true}'::jsonb, 'system'
  ),
  (
    'citation_gap_prompt_v1', 'v1', '信源缺口',
    'Generate questions that test citation coverage and source gaps without asserting facts absent from the approved knowledge base.',
	    CASE WHEN EXISTS (
	      SELECT 1 FROM pg_constraint
	      WHERE conname = 'prompt_generation_templates_status_check'
	        AND pg_get_constraintdef(oid) LIKE '%published%'
	    ) THEN 'published' ELSE 'active' END,
	    '{"intent_type":"citation_gap","built_in":true}'::jsonb, 'system'
  )
ON CONFLICT (template_key, template_version) DO UPDATE SET
  name = EXCLUDED.name,
  template_body = EXCLUDED.template_body,
  status = EXCLUDED.status,
  metadata = prompt_generation_templates.metadata || EXCLUDED.metadata,
  updated_at = now();

DROP POLICY IF EXISTS prompt_generation_templates_runtime_read ON prompt_generation_templates;
DROP POLICY IF EXISTS prompt_generation_templates_runtime_manage ON prompt_generation_templates;
CREATE POLICY prompt_generation_templates_runtime_read ON prompt_generation_templates
  FOR SELECT
  USING (true);
CREATE POLICY prompt_generation_templates_runtime_manage ON prompt_generation_templates
  FOR ALL
  USING (
    string_to_array(current_setting('app.roles', true), ',')
      && ARRAY['owner', 'admin', 'project_admin', 'internal_operator', 'system']::text[]
  )
  WITH CHECK (
    string_to_array(current_setting('app.roles', true), ',')
      && ARRAY['owner', 'admin', 'project_admin', 'internal_operator', 'system']::text[]
  );
