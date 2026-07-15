-- GEO v3 placement runtime domain.
-- All content distribution remains manual; an export is never a publication.

CREATE TABLE IF NOT EXISTS geo_products (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  brand_entity_id uuid REFERENCES brand_entities(id) ON DELETE SET NULL,
  name text NOT NULL,
  canonical_url text NOT NULL,
  category text NOT NULL,
  market_code text NOT NULL,
  external_locale text NOT NULL DEFAULT 'en-AU',
  facts jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'active',
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, canonical_url),
  CHECK (btrim(name) <> '' AND btrim(canonical_url) <> '' AND btrim(category) <> ''),
  CHECK (external_locale = 'en-AU'),
  CHECK (status IN ('draft', 'active', 'archived')),
  CHECK (jsonb_typeof(facts) = 'object')
);

CREATE TABLE IF NOT EXISTS geo_campaigns_runtime (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  product_id uuid NOT NULL REFERENCES geo_products(id) ON DELETE RESTRICT,
  name text NOT NULL,
  market_code text NOT NULL,
  external_locale text NOT NULL DEFAULT 'en-AU',
  objective text NOT NULL DEFAULT 'recommendation_influence',
  forbidden_claims text[] NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'draft',
  created_by text NOT NULL,
  updated_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, product_id, market_code),
  CHECK (btrim(name) <> '' AND objective = 'recommendation_influence'),
  CHECK (external_locale = 'en-AU'),
  CHECK (status IN ('draft', 'active', 'paused', 'archived'))
);

CREATE TABLE IF NOT EXISTS geo_campaign_queries (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  campaign_id uuid NOT NULL REFERENCES geo_campaigns_runtime(id) ON DELETE CASCADE,
  prompt_question_id uuid REFERENCES prompt_questions(id) ON DELETE SET NULL,
  query_text text NOT NULL,
  platform text NOT NULL,
  market_code text NOT NULL,
  locale text NOT NULL DEFAULT 'en-AU',
  device text NOT NULL DEFAULT 'desktop',
  sample_size integer NOT NULL DEFAULT 3,
  status text NOT NULL DEFAULT 'suggested',
  suggested_by text NOT NULL,
  approved_by text,
  approved_at timestamptz,
  frozen_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (campaign_id, query_text, platform),
  CHECK (btrim(query_text) <> ''),
  CHECK (platform IN ('chatgpt_search', 'google')),
  CHECK (locale = 'en-AU' AND sample_size BETWEEN 1 AND 10),
  CHECK (status IN ('suggested', 'approved', 'rejected', 'retired')),
  CHECK ((status = 'approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
      OR (status <> 'approved' AND approved_by IS NULL AND approved_at IS NULL))
);

CREATE TABLE IF NOT EXISTS geo_observations (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  campaign_query_id uuid NOT NULL REFERENCES geo_campaign_queries(id) ON DELETE CASCADE,
  observation_phase text NOT NULL,
  sample_index integer NOT NULL,
  observed_at timestamptz NOT NULL,
  raw_answer text NOT NULL,
  citations jsonb NOT NULL DEFAULT '[]'::jsonb,
  artifact_url text,
  visible_model text,
  market_code text NOT NULL,
  locale text NOT NULL,
  device text NOT NULL,
  imported_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (campaign_query_id, observation_phase, sample_index, observed_at),
  CHECK (observation_phase IN ('baseline', 't28', 't56', 't84', 'ad_hoc')),
  CHECK (sample_index BETWEEN 1 AND 10 AND btrim(raw_answer) <> ''),
  CHECK (jsonb_typeof(citations) = 'array')
);

CREATE TABLE IF NOT EXISTS geo_publishers (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  canonical_domain text NOT NULL UNIQUE,
  publisher_type text NOT NULL,
  policy_url text,
  status text NOT NULL DEFAULT 'unreviewed',
  policy_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  policy_checked_by text,
  policy_checked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (canonical_domain = lower(btrim(canonical_domain)) AND canonical_domain <> ''),
  CHECK (publisher_type IN ('owned_site', 'marketplace', 'video_platform', 'social_platform', 'review_platform', 'community', 'question_answer', 'editorial_media', 'other')),
  CHECK (status IN ('unreviewed', 'approved', 'restricted', 'prohibited')),
  CHECK (jsonb_typeof(policy_snapshot) = 'object')
);

INSERT INTO geo_publishers(canonical_domain, publisher_type, status, policy_snapshot)
VALUES
  ('advinsys.com.au', 'owned_site', 'unreviewed', '{}'::jsonb),
  ('amazon.com.au', 'marketplace', 'unreviewed', '{}'::jsonb),
  ('youtube.com', 'video_platform', 'unreviewed', '{}'::jsonb),
  ('tiktok.com', 'social_platform', 'unreviewed', '{}'::jsonb),
  ('instagram.com', 'social_platform', 'unreviewed', '{}'::jsonb),
  ('productreview.com.au', 'review_platform', 'unreviewed', '{}'::jsonb),
  ('reddit.com', 'community', 'unreviewed', '{}'::jsonb),
  ('ozbargain.com.au', 'community', 'unreviewed', '{}'::jsonb),
  ('quora.com', 'question_answer', 'unreviewed', '{}'::jsonb)
ON CONFLICT (canonical_domain) DO NOTHING;

CREATE TABLE IF NOT EXISTS geo_destinations (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  publisher_id uuid NOT NULL REFERENCES geo_publishers(id) ON DELETE RESTRICT,
  name text NOT NULL,
  destination_url text NOT NULL,
  task_type text NOT NULL,
  task_key text NOT NULL,
  ownership_kind text NOT NULL,
  operation_mode text NOT NULL DEFAULT 'manual_submission',
  public_disclosure_required boolean NOT NULL DEFAULT true,
  qualification_status text NOT NULL DEFAULT 'candidate',
  policy_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  policy_hash text NOT NULL,
  qualified_by text,
  qualified_at timestamptz,
  created_by text NOT NULL,
  updated_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, destination_url),
  CHECK (btrim(name) <> '' AND btrim(destination_url) <> ''),
  CHECK (task_type IN ('owned_content', 'marketplace_listing', 'video_content', 'social_content', 'business_profile', 'official_community_participation', 'deal_submission', 'expert_answer', 'editorial_submission')),
  CHECK (btrim(task_key) <> ''),
  CHECK (ownership_kind IN ('owned', 'marketplace_authorized', 'creator_authorized', 'review_platform_business', 'community_official', 'deal_platform', 'knowledge_contributor', 'third_party_editorial', 'observed_external')),
  CHECK (operation_mode IN ('observed_only', 'manual_submission')),
  CHECK (operation_mode <> 'manual_submission' OR ownership_kind <> 'observed_external'),
  CHECK (qualification_status IN ('candidate', 'approved', 'rejected', 'suspended')),
  CHECK (policy_hash ~ '^[0-9a-f]{64}$' AND jsonb_typeof(policy_snapshot) = 'object'),
  CHECK ((qualification_status = 'approved' AND qualified_by IS NOT NULL AND qualified_at IS NOT NULL)
      OR (qualification_status <> 'approved' AND qualified_by IS NULL AND qualified_at IS NULL))
);

-- The migration is idempotent for an already-running development database.
-- Fresh installs receive task_key in CREATE TABLE; upgraded local databases
-- receive it here before API traffic is allowed.
ALTER TABLE geo_destinations ADD COLUMN IF NOT EXISTS task_key text;
UPDATE geo_destinations SET task_key = task_type WHERE task_key IS NULL OR btrim(task_key) = '';
ALTER TABLE geo_destinations ALTER COLUMN task_key SET NOT NULL;

-- A destination must be able to exist as a candidate before its qualification
-- review. The command layer blocks Opportunity and Submission creation until
-- it is approved; enforcing approval at INSERT would make review impossible.
ALTER TABLE geo_destinations DROP CONSTRAINT IF EXISTS geo_destinations_check2;

CREATE TABLE IF NOT EXISTS geo_placement_opportunities (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  campaign_id uuid NOT NULL REFERENCES geo_campaigns_runtime(id) ON DELETE CASCADE,
  destination_id uuid NOT NULL REFERENCES geo_destinations(id) ON DELETE RESTRICT,
  campaign_query_id uuid REFERENCES geo_campaign_queries(id) ON DELETE SET NULL,
  title text NOT NULL,
  rationale text NOT NULL,
  priority text NOT NULL DEFAULT 'medium',
  status text NOT NULL DEFAULT 'discovered',
  created_by text NOT NULL,
  updated_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (btrim(title) <> '' AND btrim(rationale) <> ''),
  CHECK (priority IN ('low', 'medium', 'high', 'critical')),
  CHECK (status IN ('discovered', 'qualified', 'package_requested', 'ready_to_submit', 'submitted', 'published', 'verified', 'measured', 'dismissed'))
);

CREATE TABLE IF NOT EXISTS geo_prompt_templates (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  task_key text NOT NULL,
  name text NOT NULL,
  status text NOT NULL DEFAULT 'draft',
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, task_key),
  CHECK (btrim(task_key) <> '' AND btrim(name) <> ''),
  CHECK (status IN ('draft', 'published', 'archived'))
);

CREATE TABLE IF NOT EXISTS geo_prompt_template_versions (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  prompt_template_id uuid NOT NULL REFERENCES geo_prompt_templates(id) ON DELETE CASCADE,
  version_number integer NOT NULL,
  system_template text NOT NULL,
  user_template text NOT NULL,
  output_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
  template_hash text NOT NULL,
  status text NOT NULL DEFAULT 'draft',
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (prompt_template_id, version_number),
  CHECK (version_number > 0 AND btrim(system_template) <> '' AND btrim(user_template) <> ''),
  CHECK (template_hash ~ '^[0-9a-f]{64}$' AND jsonb_typeof(output_schema) = 'object'),
  CHECK (status IN ('draft', 'published', 'archived'))
);

CREATE TABLE IF NOT EXISTS geo_placement_packages (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  opportunity_id uuid NOT NULL REFERENCES geo_placement_opportunities(id) ON DELETE CASCADE,
  prompt_template_version_id uuid REFERENCES geo_prompt_template_versions(id) ON DELETE RESTRICT,
  task_key text NOT NULL,
  title text NOT NULL,
  content_json jsonb NOT NULL,
  rendered_text text NOT NULL,
  disclosure_text text,
  evidence_snapshot jsonb NOT NULL DEFAULT '[]'::jsonb,
  claim_inventory jsonb NOT NULL DEFAULT '[]'::jsonb,
  claim_inventory_complete boolean NOT NULL DEFAULT false,
  claim_inventory_reviewed_by text,
  claim_inventory_reviewed_at timestamptz,
  prompt_bundle jsonb NOT NULL DEFAULT '{}'::jsonb,
  prompt_bundle_hash text,
  qa_status text NOT NULL DEFAULT 'pending',
  qc_score numeric(5,2),
  review_notes text,
  parent_package_id uuid REFERENCES geo_placement_packages(id) ON DELETE RESTRICT,
  version_number integer NOT NULL DEFAULT 1,
  idempotency_key text,
  content_hash text NOT NULL,
  generation_model text,
  model_response_hash text,
  status text NOT NULL DEFAULT 'draft',
  submitted_for_review_by text,
  submitted_for_review_at timestamptz,
  approved_by text,
  approved_at timestamptz,
  revision_reason text,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (btrim(task_key) <> '' AND btrim(title) <> '' AND btrim(rendered_text) <> ''),
  CHECK (jsonb_typeof(content_json) = 'object' AND jsonb_typeof(evidence_snapshot) = 'array' AND jsonb_typeof(claim_inventory) = 'array'),
  CHECK (jsonb_typeof(prompt_bundle) = 'object'),
  CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  CHECK (prompt_bundle_hash IS NULL OR prompt_bundle_hash ~ '^[0-9a-f]{64}$'),
  CHECK (qa_status IN ('pending', 'passed', 'failed') AND (qc_score IS NULL OR qc_score BETWEEN 0 AND 100)),
  CHECK (version_number > 0),
  UNIQUE (project_id, opportunity_id, idempotency_key),
  CHECK (status IN ('draft', 'pending_review', 'approved', 'needs_revision', 'blocked', 'superseded')),
  CHECK ((status = 'pending_review' AND submitted_for_review_by IS NOT NULL AND submitted_for_review_at IS NOT NULL)
      OR status <> 'pending_review'),
  CHECK ((status = 'approved' AND submitted_for_review_by IS NOT NULL AND approved_by IS NOT NULL AND approved_by <> submitted_for_review_by AND approved_at IS NOT NULL)
      OR status <> 'approved')
);

-- The columns are already present on a fresh install. Keep upgrade paths
-- idempotent for development databases created by earlier v3 iterations.
ALTER TABLE geo_placement_packages ADD COLUMN IF NOT EXISTS generation_model text;
ALTER TABLE geo_placement_packages ADD COLUMN IF NOT EXISTS model_response_hash text;
ALTER TABLE geo_placement_packages ADD COLUMN IF NOT EXISTS claim_inventory_complete boolean NOT NULL DEFAULT false;
ALTER TABLE geo_placement_packages ADD COLUMN IF NOT EXISTS claim_inventory_reviewed_by text;
ALTER TABLE geo_placement_packages ADD COLUMN IF NOT EXISTS claim_inventory_reviewed_at timestamptz;
ALTER TABLE geo_placement_packages ADD COLUMN IF NOT EXISTS prompt_bundle jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE geo_placement_packages ADD COLUMN IF NOT EXISTS prompt_bundle_hash text;
ALTER TABLE geo_placement_packages ADD COLUMN IF NOT EXISTS qa_status text NOT NULL DEFAULT 'pending';
ALTER TABLE geo_placement_packages ADD COLUMN IF NOT EXISTS qc_score numeric(5,2);
ALTER TABLE geo_placement_packages ADD COLUMN IF NOT EXISTS review_notes text;
ALTER TABLE geo_placement_packages ADD COLUMN IF NOT EXISTS parent_package_id uuid REFERENCES geo_placement_packages(id) ON DELETE RESTRICT;
ALTER TABLE geo_placement_packages ADD COLUMN IF NOT EXISTS version_number integer NOT NULL DEFAULT 1;
ALTER TABLE geo_placement_packages ADD COLUMN IF NOT EXISTS idempotency_key text;
CREATE UNIQUE INDEX IF NOT EXISTS geo_packages_idempotency_idx
  ON geo_placement_packages(project_id, opportunity_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
ALTER TABLE geo_placement_packages DROP CONSTRAINT IF EXISTS geo_packages_approved_claim_inventory_complete;
ALTER TABLE geo_placement_packages ADD CONSTRAINT geo_packages_approved_claim_inventory_complete
  CHECK (status <> 'approved' OR claim_inventory_complete) NOT VALID;

CREATE TABLE IF NOT EXISTS geo_placement_submissions (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  placement_package_id uuid NOT NULL REFERENCES geo_placement_packages(id) ON DELETE RESTRICT,
  destination_id uuid NOT NULL REFERENCES geo_destinations(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'submitted',
  submitted_by text NOT NULL,
  submitted_at timestamptz NOT NULL DEFAULT now(),
  submission_evidence_url text,
  external_reference text,
  published_url text,
  published_at timestamptz,
  notes text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('submitted', 'published_url_pending_verification', 'verified', 'rejected', 'cancelled')),
  CHECK ((published_url IS NULL AND published_at IS NULL) OR (published_url IS NOT NULL AND published_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS geo_placement_verifications (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  submission_id uuid NOT NULL REFERENCES geo_placement_submissions(id) ON DELETE CASCADE,
  status text NOT NULL,
  checked_url text NOT NULL,
  content_match boolean NOT NULL DEFAULT false,
  disclosure_match boolean NOT NULL DEFAULT false,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  verified_by text NOT NULL,
  verified_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status IN ('verified', 'failed', 'unreachable')),
  CHECK (btrim(checked_url) <> '' AND jsonb_typeof(details) = 'object')
);

CREATE TABLE IF NOT EXISTS geo_measurement_windows (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  campaign_id uuid NOT NULL REFERENCES geo_campaigns_runtime(id) ON DELETE CASCADE,
  submission_id uuid NOT NULL REFERENCES geo_placement_submissions(id) ON DELETE CASCADE,
  window_key text NOT NULL,
  due_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'scheduled',
  frozen_protocol jsonb NOT NULL,
  completed_at timestamptz,
  confounded boolean NOT NULL DEFAULT false,
  confounders text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (submission_id, window_key),
  CHECK (window_key IN ('t28', 't56', 't84')),
  CHECK (status IN ('scheduled', 'running', 'completed', 'cancelled')),
  CHECK (jsonb_typeof(frozen_protocol) = 'object')
);

CREATE TABLE IF NOT EXISTS geo_measurements (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  measurement_window_id uuid NOT NULL REFERENCES geo_measurement_windows(id) ON DELETE CASCADE,
  recommendation_share numeric(8,4),
  product_mention_share numeric(8,4),
  placement_citation_share numeric(8,4),
  qualified_destination_coverage numeric(8,4),
  verified_placement_coverage numeric(8,4),
  competitive_delta numeric(8,4),
  observation_ids uuid[] NOT NULL DEFAULT '{}',
  calculated_by text NOT NULL,
  calculated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (recommendation_share IS NULL OR recommendation_share BETWEEN 0 AND 1),
  CHECK (product_mention_share IS NULL OR product_mention_share BETWEEN 0 AND 1),
  CHECK (placement_citation_share IS NULL OR placement_citation_share BETWEEN 0 AND 1),
  CHECK (qualified_destination_coverage IS NULL OR qualified_destination_coverage BETWEEN 0 AND 1),
  CHECK (verified_placement_coverage IS NULL OR verified_placement_coverage BETWEEN 0 AND 1)
);

CREATE INDEX IF NOT EXISTS geo_campaigns_runtime_project_status_idx ON geo_campaigns_runtime(project_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS geo_destinations_project_status_idx ON geo_destinations(project_id, qualification_status, updated_at DESC);
CREATE INDEX IF NOT EXISTS geo_opportunities_campaign_status_idx ON geo_placement_opportunities(campaign_id, status, priority, updated_at DESC);
CREATE INDEX IF NOT EXISTS geo_packages_opportunity_status_idx ON geo_placement_packages(opportunity_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS geo_measurement_windows_due_idx ON geo_measurement_windows(status, due_at);

CREATE UNIQUE INDEX IF NOT EXISTS geo_products_id_project_uidx ON geo_products(id, project_id);
CREATE UNIQUE INDEX IF NOT EXISTS geo_campaigns_runtime_id_project_uidx ON geo_campaigns_runtime(id, project_id);
CREATE UNIQUE INDEX IF NOT EXISTS geo_campaign_queries_id_project_uidx ON geo_campaign_queries(id, project_id);
CREATE UNIQUE INDEX IF NOT EXISTS geo_destinations_id_project_uidx ON geo_destinations(id, project_id);
CREATE UNIQUE INDEX IF NOT EXISTS geo_opportunities_id_project_uidx ON geo_placement_opportunities(id, project_id);
CREATE UNIQUE INDEX IF NOT EXISTS geo_prompt_templates_id_project_uidx ON geo_prompt_templates(id, project_id);
CREATE UNIQUE INDEX IF NOT EXISTS geo_prompt_versions_id_project_uidx ON geo_prompt_template_versions(id, project_id);
CREATE UNIQUE INDEX IF NOT EXISTS geo_packages_id_project_uidx ON geo_placement_packages(id, project_id);
CREATE UNIQUE INDEX IF NOT EXISTS geo_submissions_id_project_uidx ON geo_placement_submissions(id, project_id);
CREATE UNIQUE INDEX IF NOT EXISTS geo_windows_id_project_uidx ON geo_measurement_windows(id, project_id);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='geo_campaigns_product_project_fk') THEN
    ALTER TABLE geo_campaigns_runtime ADD CONSTRAINT geo_campaigns_product_project_fk FOREIGN KEY(product_id,project_id) REFERENCES geo_products(id,project_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='geo_queries_campaign_project_fk') THEN
    ALTER TABLE geo_campaign_queries ADD CONSTRAINT geo_queries_campaign_project_fk FOREIGN KEY(campaign_id,project_id) REFERENCES geo_campaigns_runtime(id,project_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='geo_observations_query_project_fk') THEN
    ALTER TABLE geo_observations ADD CONSTRAINT geo_observations_query_project_fk FOREIGN KEY(campaign_query_id,project_id) REFERENCES geo_campaign_queries(id,project_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='geo_opportunities_campaign_project_fk') THEN
    ALTER TABLE geo_placement_opportunities ADD CONSTRAINT geo_opportunities_campaign_project_fk FOREIGN KEY(campaign_id,project_id) REFERENCES geo_campaigns_runtime(id,project_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='geo_opportunities_destination_project_fk') THEN
    ALTER TABLE geo_placement_opportunities ADD CONSTRAINT geo_opportunities_destination_project_fk FOREIGN KEY(destination_id,project_id) REFERENCES geo_destinations(id,project_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='geo_opportunities_query_project_fk') THEN
    ALTER TABLE geo_placement_opportunities ADD CONSTRAINT geo_opportunities_query_project_fk FOREIGN KEY(campaign_query_id,project_id) REFERENCES geo_campaign_queries(id,project_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='geo_prompt_versions_template_project_fk') THEN
    ALTER TABLE geo_prompt_template_versions ADD CONSTRAINT geo_prompt_versions_template_project_fk FOREIGN KEY(prompt_template_id,project_id) REFERENCES geo_prompt_templates(id,project_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='geo_packages_opportunity_project_fk') THEN
    ALTER TABLE geo_placement_packages ADD CONSTRAINT geo_packages_opportunity_project_fk FOREIGN KEY(opportunity_id,project_id) REFERENCES geo_placement_opportunities(id,project_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='geo_packages_prompt_project_fk') THEN
    ALTER TABLE geo_placement_packages ADD CONSTRAINT geo_packages_prompt_project_fk FOREIGN KEY(prompt_template_version_id,project_id) REFERENCES geo_prompt_template_versions(id,project_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='geo_submissions_package_project_fk') THEN
    ALTER TABLE geo_placement_submissions ADD CONSTRAINT geo_submissions_package_project_fk FOREIGN KEY(placement_package_id,project_id) REFERENCES geo_placement_packages(id,project_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='geo_submissions_destination_project_fk') THEN
    ALTER TABLE geo_placement_submissions ADD CONSTRAINT geo_submissions_destination_project_fk FOREIGN KEY(destination_id,project_id) REFERENCES geo_destinations(id,project_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='geo_verifications_submission_project_fk') THEN
    ALTER TABLE geo_placement_verifications ADD CONSTRAINT geo_verifications_submission_project_fk FOREIGN KEY(submission_id,project_id) REFERENCES geo_placement_submissions(id,project_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='geo_windows_campaign_project_fk') THEN
    ALTER TABLE geo_measurement_windows ADD CONSTRAINT geo_windows_campaign_project_fk FOREIGN KEY(campaign_id,project_id) REFERENCES geo_campaigns_runtime(id,project_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='geo_windows_submission_project_fk') THEN
    ALTER TABLE geo_measurement_windows ADD CONSTRAINT geo_windows_submission_project_fk FOREIGN KEY(submission_id,project_id) REFERENCES geo_placement_submissions(id,project_id) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='geo_measurements_window_project_fk') THEN
    ALTER TABLE geo_measurements ADD CONSTRAINT geo_measurements_window_project_fk FOREIGN KEY(measurement_window_id,project_id) REFERENCES geo_measurement_windows(id,project_id) NOT VALID;
  END IF;
END $$;

DO $$
DECLARE constraint_row record;
BEGIN
  FOR constraint_row IN
    SELECT conrelid::regclass AS table_name, conname FROM pg_constraint
    WHERE conname LIKE 'geo\_%\_project\_fk' ESCAPE '\' AND NOT convalidated
  LOOP
    EXECUTE format('ALTER TABLE %s VALIDATE CONSTRAINT %I', constraint_row.table_name, constraint_row.conname);
  END LOOP;
END $$;

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'geo_products', 'geo_campaigns_runtime', 'geo_campaign_queries', 'geo_observations',
    'geo_destinations', 'geo_placement_opportunities', 'geo_prompt_templates',
    'geo_prompt_template_versions', 'geo_placement_packages', 'geo_placement_submissions',
    'geo_placement_verifications', 'geo_measurement_windows', 'geo_measurements'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON %I', table_name || '_runtime_project_isolation', table_name);
    EXECUTE format('CREATE POLICY %I ON %I USING (geo_runtime_can_access_project(project_id)) WITH CHECK (geo_runtime_can_access_project(project_id))', table_name || '_runtime_project_isolation', table_name);
  END LOOP;
END $$;

ALTER TABLE geo_publishers ENABLE ROW LEVEL SECURITY;
ALTER TABLE geo_publishers FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS geo_publishers_runtime_read ON geo_publishers;
CREATE POLICY geo_publishers_runtime_read ON geo_publishers USING (true) WITH CHECK (false);
DROP POLICY IF EXISTS geo_publishers_runtime_review ON geo_publishers;
CREATE POLICY geo_publishers_runtime_review ON geo_publishers
  FOR UPDATE USING (
    EXISTS (
      SELECT 1 FROM project_members pm
      WHERE pm.project_id = geo_runtime_project_id()
        AND lower(btrim(pm.user_id)) = lower(btrim(geo_runtime_actor_id()))
        AND pm.status = 'active' AND pm.role IN ('owner', 'admin')
    )
  ) WITH CHECK (true);

CREATE OR REPLACE FUNCTION geo_reject_published_package_content_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status <> 'draft' AND (
    NEW.content_json IS DISTINCT FROM OLD.content_json OR
    NEW.rendered_text IS DISTINCT FROM OLD.rendered_text OR
    NEW.content_hash IS DISTINCT FROM OLD.content_hash OR
    NEW.evidence_snapshot IS DISTINCT FROM OLD.evidence_snapshot OR
    NEW.claim_inventory IS DISTINCT FROM OLD.claim_inventory
  ) THEN
    RAISE EXCEPTION 'approved or submitted GEO package content is immutable';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS geo_placement_package_immutable_content ON geo_placement_packages;
CREATE TRIGGER geo_placement_package_immutable_content
  BEFORE UPDATE ON geo_placement_packages
  FOR EACH ROW EXECUTE FUNCTION geo_reject_published_package_content_change();

-- The v1 bootstrap path creates the project and its first owner in one
-- transaction. 0030 sealed normal member writes but omitted this initial
-- owner case, making new projects impossible to create through the runtime.
DROP POLICY IF EXISTS project_members_insert_initial_owner ON project_members;
CREATE POLICY project_members_insert_initial_owner ON project_members
  FOR INSERT WITH CHECK (
    project_id = geo_runtime_project_id()
    AND user_id = geo_runtime_actor_id()
    AND role IN ('owner', 'admin')
    AND status = 'active'
    AND tenant_id = (SELECT tenant_id FROM projects p WHERE p.id = project_members.project_id)
    AND NOT EXISTS (SELECT 1 FROM project_members existing WHERE existing.project_id = project_members.project_id)
  );

CREATE OR REPLACE FUNCTION geo_runtime_resolve_header_member(p_project_id uuid, p_actor_id text)
RETURNS TABLE(tenant_id uuid, role text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
  SELECT pm.tenant_id, pm.role
  FROM public.project_members pm
  WHERE pm.project_id = p_project_id
    AND lower(btrim(pm.user_id)) = lower(btrim(p_actor_id))
    AND pm.status = 'active'
  LIMIT 1;
$$;
REVOKE ALL ON FUNCTION geo_runtime_resolve_header_member(uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION geo_runtime_resolve_header_member(uuid, text) TO geo_runtime_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON geo_products, geo_campaigns_runtime,
  geo_campaign_queries, geo_observations, geo_publishers, geo_destinations,
  geo_placement_opportunities, geo_prompt_templates, geo_prompt_template_versions,
  geo_placement_packages, geo_placement_submissions, geo_placement_verifications,
  geo_measurement_windows, geo_measurements TO geo_runtime_app;
REVOKE INSERT, DELETE ON geo_publishers FROM geo_runtime_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO geo_runtime_app;
