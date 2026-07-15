-- Schema v2 B2 reporting, notification, integration and customer portal boundary.
-- This file deliberately does not create Content v2 aggregates.

CREATE TABLE reports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    report_kind text NOT NULL,
    status text NOT NULL DEFAULT 'draft',
    current_version_id uuid,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT reports_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT reports_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT reports_kind_canonical CHECK (report_kind IN (
        'geo_visibility', 'opportunity', 'retest', 'executive_summary', 'custom'
    )),
    CONSTRAINT reports_status_canonical CHECK (status IN (
        'draft', 'generating', 'pending_review', 'approved', 'revoked', 'archived'
    )),
    CONSTRAINT reports_values_valid CHECK (btrim(created_by) <> '' AND updated_at >= created_at)
);

CREATE TABLE report_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    report_id uuid NOT NULL,
    version_number integer NOT NULL,
    generation_job_id uuid,
    title text NOT NULL,
    locale text NOT NULL DEFAULT 'en-AU',
    rendered_markdown text NOT NULL,
    content_hash text NOT NULL,
    methodology_hash text NOT NULL,
    input_snapshot_hash text NOT NULL,
    status text NOT NULL DEFAULT 'pending_review',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    approved_by text,
    approved_at timestamptz,
    revoked_by text,
    revoked_at timestamptz,
    revoke_reason text,
    CONSTRAINT report_versions_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT report_versions_report_project_fkey FOREIGN KEY (report_id, project_id)
        REFERENCES reports(id, project_id) ON DELETE CASCADE,
    CONSTRAINT report_versions_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT report_versions_report_number_unique UNIQUE (report_id, version_number),
    CONSTRAINT report_versions_hashes_sha256 CHECK (
        content_hash ~ '^[0-9a-f]{64}$' AND methodology_hash ~ '^[0-9a-f]{64}$'
        AND input_snapshot_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT report_versions_values_valid CHECK (
        version_number > 0 AND btrim(title) <> '' AND btrim(rendered_markdown) <> ''
        AND btrim(created_by) <> '' AND locale IN ('en-AU', 'zh-CN')
    ),
    CONSTRAINT report_versions_status_canonical CHECK (
        status IN ('pending_review', 'approved', 'revoked', 'superseded')
    ),
    CONSTRAINT report_versions_lifecycle CHECK (
        (status = 'pending_review' AND approved_by IS NULL AND approved_at IS NULL
            AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason IS NULL)
        OR (status = 'approved' AND approved_by IS NOT NULL AND btrim(approved_by) <> ''
            AND approved_at IS NOT NULL AND revoked_by IS NULL AND revoked_at IS NULL
            AND revoke_reason IS NULL)
        OR (status = 'revoked' AND approved_by IS NOT NULL AND approved_at IS NOT NULL
            AND revoked_by IS NOT NULL AND btrim(revoked_by) <> '' AND revoked_at IS NOT NULL
            AND revoke_reason IS NOT NULL AND btrim(revoke_reason) <> '')
        OR (status = 'superseded' AND approved_by IS NOT NULL AND approved_at IS NOT NULL
            AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason IS NULL)
    )
);
ALTER TABLE reports ADD CONSTRAINT reports_current_version_project_fkey
    FOREIGN KEY (current_version_id, project_id) REFERENCES report_versions(id, project_id)
    DEFERRABLE INITIALLY DEFERRED;

-- Stable report export identity retained for Opportunity and future Content lineage.
CREATE TABLE report_exports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    report_version_id uuid NOT NULL,
    export_format text NOT NULL,
    evidence_asset_id uuid NOT NULL,
    artifact_hash text NOT NULL,
    exported_by text NOT NULL,
    exported_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT report_exports_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT report_exports_version_project_fkey FOREIGN KEY (report_version_id, project_id)
        REFERENCES report_versions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT report_exports_asset_project_fkey FOREIGN KEY (evidence_asset_id, project_id)
        REFERENCES evidence_assets(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT report_exports_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT report_exports_format_canonical CHECK (export_format IN ('markdown', 'pdf', 'csv', 'json')),
    CONSTRAINT report_exports_hash_sha256 CHECK (artifact_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT report_exports_values_valid CHECK (btrim(exported_by) <> ''),
    CONSTRAINT report_exports_unique UNIQUE (report_version_id, export_format)
);

CREATE TABLE report_version_score_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, project_id uuid NOT NULL,
    report_version_id uuid NOT NULL, visibility_score_snapshot_id uuid NOT NULL, source_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT rv_scores_project_tenant_fkey FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT rv_scores_version_project_fkey FOREIGN KEY (report_version_id, project_id) REFERENCES report_versions(id, project_id) ON DELETE CASCADE,
    CONSTRAINT rv_scores_snapshot_project_fkey FOREIGN KEY (visibility_score_snapshot_id, project_id) REFERENCES visibility_score_snapshots(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT rv_scores_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT rv_scores_role_canonical CHECK (source_role IN ('primary', 'baseline', 'comparison')),
    CONSTRAINT rv_scores_unique UNIQUE (report_version_id, visibility_score_snapshot_id, source_role)
);
CREATE TABLE report_version_retests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, project_id uuid NOT NULL,
    report_version_id uuid NOT NULL, retest_run_id uuid NOT NULL, source_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT rv_retests_project_tenant_fkey FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT rv_retests_version_project_fkey FOREIGN KEY (report_version_id, project_id) REFERENCES report_versions(id, project_id) ON DELETE CASCADE,
    CONSTRAINT rv_retests_run_project_fkey FOREIGN KEY (retest_run_id, project_id) REFERENCES retest_runs(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT rv_retests_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT rv_retests_role_canonical CHECK (source_role IN ('primary', 'comparison')),
    CONSTRAINT rv_retests_unique UNIQUE (report_version_id, retest_run_id, source_role)
);
CREATE TABLE report_version_facts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, project_id uuid NOT NULL,
    report_version_id uuid NOT NULL, knowledge_fact_version_id uuid NOT NULL, evidence_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT rv_facts_project_tenant_fkey FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT rv_facts_version_project_fkey FOREIGN KEY (report_version_id, project_id) REFERENCES report_versions(id, project_id) ON DELETE CASCADE,
    CONSTRAINT rv_facts_fact_project_fkey FOREIGN KEY (knowledge_fact_version_id, project_id) REFERENCES knowledge_fact_versions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT rv_facts_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT rv_facts_role_canonical CHECK (evidence_role IN ('finding', 'citation', 'methodology')),
    CONSTRAINT rv_facts_unique UNIQUE (report_version_id, knowledge_fact_version_id, evidence_role)
);
CREATE TABLE report_version_actions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, project_id uuid NOT NULL,
    report_version_id uuid NOT NULL, action_recommendation_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT rv_actions_project_tenant_fkey FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT rv_actions_version_project_fkey FOREIGN KEY (report_version_id, project_id) REFERENCES report_versions(id, project_id) ON DELETE CASCADE,
    CONSTRAINT rv_actions_action_project_fkey FOREIGN KEY (action_recommendation_id, project_id) REFERENCES action_recommendations(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT rv_actions_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT rv_actions_unique UNIQUE (report_version_id, action_recommendation_id)
);

CREATE TABLE report_generation_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, project_id uuid NOT NULL,
    report_id uuid NOT NULL, requested_version_number integer NOT NULL, idempotency_key text NOT NULL,
    replay_nonce integer NOT NULL DEFAULT 0, input_snapshot jsonb NOT NULL, input_snapshot_hash text NOT NULL,
    status text NOT NULL DEFAULT 'queued', priority integer NOT NULL DEFAULT 0,
    attempt_count integer NOT NULL DEFAULT 0, max_attempts integer NOT NULL DEFAULT 3,
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(), lease_owner text, lease_token uuid,
    lease_expires_at timestamptz, heartbeat_at timestamptz, started_at timestamptz, completed_at timestamptz,
    completed_by text, output_report_version_id uuid, last_error_code text, last_error_message text,
    requested_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT report_jobs_project_tenant_fkey FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT report_jobs_report_project_fkey FOREIGN KEY (report_id, project_id) REFERENCES reports(id, project_id) ON DELETE CASCADE,
    CONSTRAINT report_jobs_output_project_fkey FOREIGN KEY (output_report_version_id, project_id) REFERENCES report_versions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT report_jobs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT report_jobs_idempotency_unique UNIQUE (project_id, idempotency_key),
    CONSTRAINT report_jobs_version_unique UNIQUE (report_id, requested_version_number),
    CONSTRAINT report_jobs_hash_sha256 CHECK (input_snapshot_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT report_jobs_input_object CHECK (jsonb_typeof(input_snapshot) = 'object'),
    CONSTRAINT report_jobs_values_valid CHECK (requested_version_number > 0 AND replay_nonce >= 0 AND btrim(idempotency_key) <> '' AND btrim(requested_by) <> ''),
    CONSTRAINT report_jobs_status_canonical CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'dead_lettered')),
    CONSTRAINT report_jobs_attempts_valid CHECK (attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts),
    CONSTRAINT report_jobs_error_pair CHECK ((last_error_code IS NULL AND last_error_message IS NULL) OR (last_error_code IS NOT NULL AND btrim(last_error_code) <> '' AND last_error_message IS NOT NULL AND btrim(last_error_message) <> '')),
    CONSTRAINT report_jobs_lease_lifecycle CHECK (
        (status = 'queued' AND lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL AND completed_at IS NULL AND completed_by IS NULL AND output_report_version_id IS NULL)
        OR (status = 'running' AND lease_owner IS NOT NULL AND btrim(lease_owner) <> '' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL AND started_at IS NOT NULL AND completed_at IS NULL AND completed_by IS NULL)
        OR (status = 'succeeded' AND lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL AND completed_at IS NOT NULL AND completed_by IS NOT NULL AND btrim(completed_by) <> '' AND output_report_version_id IS NOT NULL)
        OR (status IN ('failed', 'cancelled', 'dead_lettered') AND lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL AND completed_at IS NOT NULL AND completed_by IS NOT NULL AND btrim(completed_by) <> '' AND output_report_version_id IS NULL)
    )
);
ALTER TABLE report_versions ADD CONSTRAINT report_versions_generation_job_project_fkey
    FOREIGN KEY (generation_job_id, project_id)
    REFERENCES report_generation_jobs(id, project_id) ON DELETE RESTRICT;

-- Incremental extension of 0030's outbox. The replacement trigger retains all
-- Collection, Scoring, Retest, and six typed Knowledge branches before adding Reports.
ALTER TABLE durable_job_dispatch_outbox ADD COLUMN report_generation_job_id uuid;
ALTER TABLE durable_job_dispatch_outbox ADD CONSTRAINT durable_dispatch_report_project_fkey
    FOREIGN KEY (report_generation_job_id, project_id) REFERENCES report_generation_jobs(id, project_id) ON DELETE CASCADE;
ALTER TABLE durable_job_dispatch_outbox DROP CONSTRAINT durable_dispatch_kind_canonical, DROP CONSTRAINT durable_dispatch_job_discriminator;
ALTER TABLE durable_job_dispatch_outbox ADD CONSTRAINT durable_dispatch_kind_canonical CHECK (job_kind IN ('collection','visibility_score','retest','knowledge_import','knowledge_crawl','knowledge_parse','knowledge_chunk','knowledge_embed','knowledge_fact_extract','report_generation'));
ALTER TABLE durable_job_dispatch_outbox ADD CONSTRAINT durable_dispatch_job_discriminator CHECK (
 (job_kind='collection' AND collection_job_id=job_id AND visibility_score_run_id IS NULL AND retest_run_id IS NULL AND knowledge_pipeline_job_id IS NULL AND report_generation_job_id IS NULL) OR
 (job_kind='visibility_score' AND visibility_score_run_id=job_id AND collection_job_id IS NULL AND retest_run_id IS NULL AND knowledge_pipeline_job_id IS NULL AND report_generation_job_id IS NULL) OR
 (job_kind='retest' AND retest_run_id=job_id AND collection_job_id IS NULL AND visibility_score_run_id IS NULL AND knowledge_pipeline_job_id IS NULL AND report_generation_job_id IS NULL) OR
 (job_kind IN ('knowledge_import','knowledge_crawl','knowledge_parse','knowledge_chunk','knowledge_embed','knowledge_fact_extract') AND knowledge_pipeline_job_id=job_id AND collection_job_id IS NULL AND visibility_score_run_id IS NULL AND retest_run_id IS NULL AND report_generation_job_id IS NULL) OR
 (job_kind='report_generation' AND report_generation_job_id=job_id AND collection_job_id IS NULL AND visibility_score_run_id IS NULL AND retest_run_id IS NULL AND knowledge_pipeline_job_id IS NULL)
);
CREATE OR REPLACE FUNCTION geo_v2_enqueue_durable_job_dispatch() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE canonical_kind text; canonical_payload_hash text; BEGIN
 IF TG_TABLE_NAME='knowledge_pipeline_jobs' THEN canonical_kind:='knowledge_'||NEW.job_type;
 ELSIF TG_TABLE_NAME='collection_jobs' THEN canonical_kind:='collection';
 ELSIF TG_TABLE_NAME='visibility_score_runs' THEN canonical_kind:='visibility_score';
 ELSIF TG_TABLE_NAME='retest_runs' THEN canonical_kind:='retest';
 ELSIF TG_TABLE_NAME='report_generation_jobs' THEN canonical_kind:='report_generation';
 ELSE RAISE EXCEPTION 'unsupported durable job dispatch source' USING ERRCODE='23514'; END IF;
 canonical_payload_hash:=encode(public.digest(jsonb_build_object('job_kind',canonical_kind,'job_id',NEW.id,'project_id',NEW.project_id,'idempotency_key',NEW.idempotency_key,'replay_nonce',NEW.replay_nonce)::text,'sha256'),'hex');
 INSERT INTO public.durable_job_dispatch_outbox(tenant_id,project_id,job_kind,job_id,collection_job_id,visibility_score_run_id,retest_run_id,knowledge_pipeline_job_id,report_generation_job_id,payload_hash)
 VALUES(NEW.tenant_id,NEW.project_id,canonical_kind,NEW.id,CASE WHEN canonical_kind='collection' THEN NEW.id END,CASE WHEN canonical_kind='visibility_score' THEN NEW.id END,CASE WHEN canonical_kind='retest' THEN NEW.id END,CASE WHEN canonical_kind LIKE 'knowledge_%' THEN NEW.id END,CASE WHEN canonical_kind='report_generation' THEN NEW.id END,canonical_payload_hash); RETURN NEW; END; $$;
CREATE TRIGGER report_jobs_enqueue_dispatch AFTER INSERT ON report_generation_jobs FOR EACH ROW EXECUTE FUNCTION geo_v2_enqueue_durable_job_dispatch();

CREATE FUNCTION geo_v2_claim_report_generation_job(
    p_worker_id text, p_lease_seconds integer, p_project_id uuid DEFAULT NULL
) RETURNS SETOF report_generation_jobs
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_worker_id IS NULL OR btrim(p_worker_id)='' OR p_lease_seconds NOT BETWEEN 5 AND 3600 THEN
  RAISE EXCEPTION 'report claim arguments are invalid' USING ERRCODE='22023'; END IF;
 UPDATE public.report_generation_jobs SET status='dead_lettered',lease_owner=NULL,lease_token=NULL,
  lease_expires_at=NULL,heartbeat_at=NULL,completed_at=statement_timestamp(),completed_by='lease-recovery',
  last_error_code='attempts_exhausted',last_error_message='report job lease expired after attempt budget',updated_at=statement_timestamp()
 WHERE status='running' AND lease_expires_at<=statement_timestamp() AND attempt_count>=max_attempts;
 RETURN QUERY WITH candidate AS (
  SELECT id FROM public.report_generation_jobs WHERE ((status='queued' AND next_attempt_at<=statement_timestamp()) OR (status='running' AND lease_expires_at<=statement_timestamp()))
   AND attempt_count<max_attempts AND (p_project_id IS NULL OR project_id=p_project_id)
  ORDER BY priority DESC,next_attempt_at,created_at,id FOR UPDATE SKIP LOCKED LIMIT 1
 ) UPDATE public.report_generation_jobs j SET status='running',attempt_count=j.attempt_count+1,
  lease_owner=btrim(p_worker_id),lease_token=gen_random_uuid(),lease_expires_at=statement_timestamp()+make_interval(secs=>p_lease_seconds),heartbeat_at=statement_timestamp(),started_at=coalesce(j.started_at,statement_timestamp()),updated_at=statement_timestamp()
 FROM candidate WHERE j.id=candidate.id RETURNING j.*;
END; $$;
CREATE FUNCTION geo_v2_heartbeat_report_generation_job(p_job_id uuid,p_worker_id text,p_lease_token uuid,p_lease_seconds integer)
RETURNS report_generation_jobs LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r public.report_generation_jobs%ROWTYPE; BEGIN
 UPDATE public.report_generation_jobs SET lease_expires_at=statement_timestamp()+make_interval(secs=>p_lease_seconds),heartbeat_at=statement_timestamp(),updated_at=statement_timestamp()
 WHERE id=p_job_id AND status='running' AND lease_owner=btrim(p_worker_id) AND lease_token=p_lease_token AND lease_expires_at>statement_timestamp() RETURNING * INTO r;
 IF NOT FOUND THEN RAISE EXCEPTION 'report job lease is lost' USING ERRCODE='55000'; END IF; RETURN r; END; $$;
CREATE FUNCTION geo_v2_complete_report_generation_job(p_job_id uuid,p_worker_id text,p_lease_token uuid,p_report_version_id uuid)
RETURNS report_generation_jobs LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r public.report_generation_jobs%ROWTYPE; BEGIN
 UPDATE public.report_generation_jobs j SET status='succeeded',lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,completed_at=statement_timestamp(),completed_by=btrim(p_worker_id),output_report_version_id=p_report_version_id,updated_at=statement_timestamp()
 WHERE id=p_job_id AND status='running' AND lease_owner=btrim(p_worker_id) AND lease_token=p_lease_token AND lease_expires_at>statement_timestamp()
  AND EXISTS(SELECT 1 FROM public.report_versions v WHERE v.id=p_report_version_id AND v.project_id=j.project_id AND v.generation_job_id=j.id)
 RETURNING j.* INTO r; IF NOT FOUND THEN RAISE EXCEPTION 'report completion rejected by lease or lineage' USING ERRCODE='55000'; END IF; RETURN r; END; $$;
CREATE FUNCTION geo_v2_fail_report_generation_job(p_job_id uuid,p_worker_id text,p_lease_token uuid,p_error_code text,p_error_message text,p_retryable boolean,p_retry_delay_seconds integer DEFAULT 0)
RETURNS report_generation_jobs LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r public.report_generation_jobs%ROWTYPE; BEGIN
 UPDATE public.report_generation_jobs j SET status=CASE WHEN p_retryable AND j.attempt_count<j.max_attempts THEN 'queued' ELSE 'failed' END,
  next_attempt_at=CASE WHEN p_retryable AND j.attempt_count<j.max_attempts THEN statement_timestamp()+make_interval(secs=>p_retry_delay_seconds) ELSE j.next_attempt_at END,
  lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,completed_at=CASE WHEN p_retryable AND j.attempt_count<j.max_attempts THEN NULL ELSE statement_timestamp() END,
  completed_by=CASE WHEN p_retryable AND j.attempt_count<j.max_attempts THEN NULL ELSE btrim(p_worker_id) END,last_error_code=btrim(p_error_code),last_error_message=btrim(p_error_message),updated_at=statement_timestamp()
 WHERE id=p_job_id AND status='running' AND lease_owner=btrim(p_worker_id) AND lease_token=p_lease_token AND lease_expires_at>statement_timestamp() RETURNING j.* INTO r;
 IF NOT FOUND THEN RAISE EXCEPTION 'report job lease is lost' USING ERRCODE='55000'; END IF; RETURN r; END; $$;
CREATE FUNCTION geo_v2_create_report_generation_job(
    p_tenant_id uuid,p_project_id uuid,p_report_id uuid,p_idempotency_key text,
    p_input_snapshot jsonb,p_requested_by text
) RETURNS report_generation_jobs
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r public.report_generation_jobs%ROWTYPE; h text; next_version integer; BEGIN
 IF NOT public.geo_v2_session_has_project_permission(p_project_id,p_tenant_id,'report.generate') THEN
  RAISE EXCEPTION 'report generation permission denied' USING ERRCODE='42501'; END IF;
 IF p_idempotency_key IS NULL OR btrim(p_idempotency_key)='' OR jsonb_typeof(p_input_snapshot)<>'object' OR p_requested_by IS NULL OR btrim(p_requested_by)='' THEN
  RAISE EXCEPTION 'report job arguments are invalid' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(p_project_id::text||':'||btrim(p_idempotency_key),0));
 h:=encode(public.digest(p_input_snapshot::text,'sha256'),'hex');
 SELECT * INTO r FROM public.report_generation_jobs WHERE project_id=p_project_id AND idempotency_key=btrim(p_idempotency_key);
 IF FOUND THEN
  IF r.report_id<>p_report_id OR r.input_snapshot_hash<>h THEN RAISE EXCEPTION 'report idempotency key conflicts with prior input' USING ERRCODE='23505'; END IF;
  RETURN r;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM public.reports WHERE id=p_report_id AND project_id=p_project_id AND tenant_id=p_tenant_id) THEN RAISE EXCEPTION 'report is outside project' USING ERRCODE='23514'; END IF;
 SELECT coalesce(max(version_number),0)+1 INTO next_version FROM public.report_versions WHERE report_id=p_report_id;
 INSERT INTO public.report_generation_jobs(tenant_id,project_id,report_id,requested_version_number,idempotency_key,input_snapshot,input_snapshot_hash,requested_by)
 VALUES(p_tenant_id,p_project_id,p_report_id,next_version,btrim(p_idempotency_key),p_input_snapshot,h,btrim(p_requested_by)) RETURNING * INTO r;
 UPDATE public.reports SET status='generating',updated_at=statement_timestamp() WHERE id=p_report_id AND project_id=p_project_id;
 RETURN r;
END; $$;

CREATE FUNCTION geo_v2_persist_report_generation_result(
    p_job_id uuid, p_worker_id text, p_lease_token uuid, p_title text,
    p_locale text, p_rendered_markdown text, p_content_hash text,
    p_methodology_hash text
) RETURNS report_versions
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE j public.report_generation_jobs%ROWTYPE; v public.report_versions%ROWTYPE;
BEGIN
 SELECT * INTO j FROM public.report_generation_jobs
 WHERE id=p_job_id AND status='running' AND lease_owner=btrim(p_worker_id)
   AND lease_token=p_lease_token AND lease_expires_at>statement_timestamp()
 FOR UPDATE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'report result persistence rejected by lease' USING ERRCODE='55000';
 END IF;
 IF p_title IS NULL OR btrim(p_title)='' OR p_rendered_markdown IS NULL
    OR btrim(p_rendered_markdown)='' OR p_locale NOT IN ('en-AU','zh-CN')
    OR p_content_hash !~ '^[0-9a-f]{64}$' OR p_methodology_hash !~ '^[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'report result arguments are invalid' USING ERRCODE='22023';
 END IF;
 INSERT INTO public.report_versions(
   tenant_id, project_id, report_id, version_number, generation_job_id, title,
   locale, rendered_markdown, content_hash, methodology_hash, input_snapshot_hash,
   created_by
 ) VALUES (
   j.tenant_id, j.project_id, j.report_id, j.requested_version_number, j.id,
   btrim(p_title), p_locale, p_rendered_markdown, p_content_hash,
   p_methodology_hash, j.input_snapshot_hash, btrim(p_worker_id)
 ) RETURNING * INTO v;
 RETURN v;
END; $$;

CREATE TABLE integration_connectors (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, project_id uuid NOT NULL,
    connector_kind text NOT NULL, display_name text NOT NULL, status text NOT NULL DEFAULT 'disabled',
    secret_reference text, configuration jsonb NOT NULL DEFAULT '{}'::jsonb, configuration_hash text NOT NULL,
    created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_by text NOT NULL, updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT connectors_project_tenant_fkey FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT connectors_id_project_unique UNIQUE (id, project_id), CONSTRAINT connectors_unique UNIQUE (project_id, connector_kind, display_name),
    CONSTRAINT connectors_kind_canonical CHECK (connector_kind IN ('webhook','email','wordpress','webflow','shopify','linkedin','youtube','google_business')),
    CONSTRAINT connectors_status_canonical CHECK (status IN ('disabled','active','revoked')),
    CONSTRAINT connectors_values_valid CHECK (btrim(display_name)<>'' AND btrim(created_by)<>'' AND btrim(updated_by)<>'' AND configuration_hash ~ '^[0-9a-f]{64}$' AND jsonb_typeof(configuration)='object' AND (secret_reference IS NULL OR secret_reference ~ '^[a-z][a-z0-9+.-]*://[^[:space:]]+$')),
    CONSTRAINT connectors_time_order CHECK (updated_at >= created_at)
);
CREATE TABLE notification_recipients (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, project_id uuid NOT NULL,
    recipient_kind text NOT NULL, actor_id text, destination_reference text, status text NOT NULL DEFAULT 'active', created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT recipients_project_tenant_fkey FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT recipients_id_project_unique UNIQUE (id, project_id), CONSTRAINT recipients_kind_canonical CHECK (recipient_kind IN ('project_member','connector_destination')),
    CONSTRAINT recipients_target_coherent CHECK ((recipient_kind='project_member' AND actor_id IS NOT NULL AND btrim(actor_id)<>'' AND destination_reference IS NULL) OR (recipient_kind='connector_destination' AND actor_id IS NULL AND destination_reference IS NOT NULL AND btrim(destination_reference)<>'')),
    CONSTRAINT recipients_status_canonical CHECK (status IN ('active','disabled')), CONSTRAINT recipients_values_valid CHECK (btrim(created_by)<>''),
    CONSTRAINT recipients_unique UNIQUE NULLS NOT DISTINCT (project_id,recipient_kind,actor_id,destination_reference)
);
CREATE TABLE notifications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, project_id uuid NOT NULL,
    event_type text NOT NULL, severity text NOT NULL DEFAULT 'info', title text NOT NULL, body text NOT NULL,
    target_type text NOT NULL, target_id uuid, payload_hash text NOT NULL, created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT notifications_project_tenant_fkey FOREIGN KEY (project_id,tenant_id) REFERENCES projects(id,tenant_id) ON DELETE CASCADE,
    CONSTRAINT notifications_id_project_unique UNIQUE(id,project_id), CONSTRAINT notifications_values_valid CHECK(btrim(event_type)<>'' AND btrim(title)<>'' AND btrim(body)<>'' AND btrim(target_type)<>'' AND btrim(created_by)<>'' AND payload_hash ~ '^[0-9a-f]{64}$'), CONSTRAINT notifications_severity_canonical CHECK(severity IN ('info','low','medium','high','critical'))
);
CREATE TABLE notification_deliveries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, project_id uuid NOT NULL, notification_id uuid NOT NULL, recipient_id uuid NOT NULL, connector_id uuid,
    status text NOT NULL DEFAULT 'queued', attempt_count integer NOT NULL DEFAULT 0, max_attempts integer NOT NULL DEFAULT 3, next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(), lease_owner text, lease_token uuid, lease_expires_at timestamptz, heartbeat_at timestamptz, delivered_at timestamptz, read_at timestamptz, response_hash text, last_error_code text, last_error_message text, created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT deliveries_project_tenant_fkey FOREIGN KEY(project_id,tenant_id) REFERENCES projects(id,tenant_id) ON DELETE CASCADE, CONSTRAINT deliveries_notification_project_fkey FOREIGN KEY(notification_id,project_id) REFERENCES notifications(id,project_id) ON DELETE CASCADE, CONSTRAINT deliveries_recipient_project_fkey FOREIGN KEY(recipient_id,project_id) REFERENCES notification_recipients(id,project_id) ON DELETE RESTRICT, CONSTRAINT deliveries_connector_project_fkey FOREIGN KEY(connector_id,project_id) REFERENCES integration_connectors(id,project_id) ON DELETE RESTRICT,
    CONSTRAINT deliveries_id_project_unique UNIQUE(id,project_id), CONSTRAINT deliveries_unique UNIQUE(notification_id,recipient_id,connector_id), CONSTRAINT deliveries_status_canonical CHECK(status IN ('queued','running','delivered','failed','dead_lettered','cancelled')), CONSTRAINT deliveries_attempts_valid CHECK(attempt_count>=0 AND max_attempts>0 AND attempt_count<=max_attempts), CONSTRAINT deliveries_error_pair CHECK((last_error_code IS NULL AND last_error_message IS NULL) OR (last_error_code IS NOT NULL AND btrim(last_error_code)<>'' AND last_error_message IS NOT NULL AND btrim(last_error_message)<>'')), CONSTRAINT deliveries_lease_lifecycle CHECK((status='queued' AND lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL AND delivered_at IS NULL) OR (status='running' AND lease_owner IS NOT NULL AND btrim(lease_owner)<>'' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL AND delivered_at IS NULL) OR (status='delivered' AND lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL AND delivered_at IS NOT NULL) OR (status IN ('failed','dead_lettered','cancelled') AND lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL AND delivered_at IS NULL))
);
CREATE TABLE portal_project_settings (project_id uuid PRIMARY KEY,tenant_id uuid NOT NULL,enabled boolean NOT NULL DEFAULT false,customer_label text,updated_by text NOT NULL,updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),CONSTRAINT portal_settings_project_tenant_fkey FOREIGN KEY(project_id,tenant_id) REFERENCES projects(id,tenant_id) ON DELETE CASCADE,CONSTRAINT portal_settings_values_valid CHECK(btrim(updated_by)<>'' AND (customer_label IS NULL OR btrim(customer_label)<>'')));
CREATE TABLE portal_report_visibility (id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,project_id uuid NOT NULL,report_version_id uuid NOT NULL,visible boolean NOT NULL DEFAULT true,visible_by text NOT NULL,visible_at timestamptz NOT NULL DEFAULT clock_timestamp(),CONSTRAINT portal_report_visibility_project_tenant_fkey FOREIGN KEY(project_id,tenant_id) REFERENCES projects(id,tenant_id) ON DELETE CASCADE,CONSTRAINT portal_report_visibility_version_project_fkey FOREIGN KEY(report_version_id,project_id) REFERENCES report_versions(id,project_id) ON DELETE CASCADE,CONSTRAINT portal_report_visibility_id_project_unique UNIQUE(id,project_id),CONSTRAINT portal_report_visibility_version_unique UNIQUE(report_version_id),CONSTRAINT portal_report_visibility_actor_nonempty CHECK(btrim(visible_by)<>''));

CREATE FUNCTION geo_v2_claim_notification_delivery(p_worker_id text,p_lease_seconds integer,p_project_id uuid DEFAULT NULL) RETURNS SETOF notification_deliveries LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN IF p_worker_id IS NULL OR btrim(p_worker_id)='' OR p_lease_seconds NOT BETWEEN 5 AND 3600 THEN RAISE EXCEPTION 'notification claim arguments are invalid' USING ERRCODE='22023'; END IF; UPDATE public.notification_deliveries SET status='dead_lettered',lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,last_error_code='attempts_exhausted',last_error_message='notification delivery lease expired after attempt budget',updated_at=statement_timestamp() WHERE status='running' AND lease_expires_at<=statement_timestamp() AND attempt_count>=max_attempts; RETURN QUERY WITH candidate AS(SELECT id FROM public.notification_deliveries WHERE ((status='queued' AND next_attempt_at<=statement_timestamp()) OR(status='running' AND lease_expires_at<=statement_timestamp())) AND attempt_count<max_attempts AND(p_project_id IS NULL OR project_id=p_project_id) ORDER BY next_attempt_at,created_at,id FOR UPDATE SKIP LOCKED LIMIT 1) UPDATE public.notification_deliveries d SET status='running',attempt_count=d.attempt_count+1,lease_owner=btrim(p_worker_id),lease_token=gen_random_uuid(),lease_expires_at=statement_timestamp()+make_interval(secs=>p_lease_seconds),heartbeat_at=statement_timestamp(),updated_at=statement_timestamp() FROM candidate WHERE d.id=candidate.id RETURNING d.*; END; $$;
CREATE FUNCTION geo_v2_heartbeat_notification_delivery(p_delivery_id uuid,p_worker_id text,p_lease_token uuid,p_lease_seconds integer) RETURNS notification_deliveries LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$ DECLARE r public.notification_deliveries%ROWTYPE; BEGIN UPDATE public.notification_deliveries SET lease_expires_at=statement_timestamp()+make_interval(secs=>p_lease_seconds),heartbeat_at=statement_timestamp(),updated_at=statement_timestamp() WHERE id=p_delivery_id AND status='running' AND lease_owner=btrim(p_worker_id) AND lease_token=p_lease_token AND lease_expires_at>statement_timestamp() RETURNING * INTO r; IF NOT FOUND THEN RAISE EXCEPTION 'notification delivery lease is lost' USING ERRCODE='55000'; END IF;RETURN r;END; $$;
CREATE FUNCTION geo_v2_complete_notification_delivery(p_delivery_id uuid,p_worker_id text,p_lease_token uuid,p_response_hash text) RETURNS notification_deliveries LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$ DECLARE r public.notification_deliveries%ROWTYPE; BEGIN UPDATE public.notification_deliveries SET status='delivered',lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,delivered_at=statement_timestamp(),response_hash=p_response_hash,updated_at=statement_timestamp() WHERE id=p_delivery_id AND status='running' AND lease_owner=btrim(p_worker_id) AND lease_token=p_lease_token AND lease_expires_at>statement_timestamp() AND p_response_hash ~ '^[0-9a-f]{64}$' RETURNING * INTO r;IF NOT FOUND THEN RAISE EXCEPTION 'notification delivery completion rejected' USING ERRCODE='55000';END IF;RETURN r;END; $$;
CREATE FUNCTION geo_v2_fail_notification_delivery(p_delivery_id uuid,p_worker_id text,p_lease_token uuid,p_error_code text,p_error_message text,p_retryable boolean,p_retry_delay_seconds integer DEFAULT 0) RETURNS notification_deliveries LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$ DECLARE r public.notification_deliveries%ROWTYPE; BEGIN UPDATE public.notification_deliveries d SET status=CASE WHEN p_retryable AND d.attempt_count<d.max_attempts THEN 'queued' ELSE 'failed' END,next_attempt_at=CASE WHEN p_retryable AND d.attempt_count<d.max_attempts THEN statement_timestamp()+make_interval(secs=>p_retry_delay_seconds) ELSE d.next_attempt_at END,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,last_error_code=btrim(p_error_code),last_error_message=btrim(p_error_message),updated_at=statement_timestamp() WHERE id=p_delivery_id AND status='running' AND lease_owner=btrim(p_worker_id) AND lease_token=p_lease_token AND lease_expires_at>statement_timestamp() RETURNING d.* INTO r;IF NOT FOUND THEN RAISE EXCEPTION 'notification delivery lease is lost' USING ERRCODE='55000';END IF;RETURN r;END; $$;

CREATE FUNCTION geo_v2_read_portal_reports(p_project_id uuid)
RETURNS TABLE(report_export_id uuid,report_title text,locale text,content_hash text,artifact_format text,artifact_hash text,approved_at timestamptz)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT e.id,v.title,v.locale,v.content_hash,e.export_format,e.artifact_hash,v.approved_at
 FROM public.portal_project_settings s
 JOIN public.portal_report_visibility pv ON pv.project_id=s.project_id AND pv.visible
 JOIN public.report_versions v ON v.id=pv.report_version_id AND v.project_id=s.project_id AND v.status='approved'
 JOIN public.report_exports e ON e.report_version_id=v.id AND e.project_id=s.project_id
 WHERE s.project_id=p_project_id AND s.enabled
   AND EXISTS (SELECT 1 FROM public.geo_v2_resolve_session_context() c
       CROSS JOIN LATERAL jsonb_array_elements(c.project_scopes) scope(value)
       CROSS JOIN LATERAL jsonb_array_elements_text(scope.value->'roles') role_item(role_name)
       WHERE c.tenant_id=s.tenant_id AND scope.value->>'project_id'=p_project_id::text
         AND role_item.role_name='client_viewer');
$$;

CREATE FUNCTION geo_v2_reject_report_immutable_update() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN RAISE EXCEPTION 'report traceability rows are immutable' USING ERRCODE='55000'; END; $$;
CREATE FUNCTION geo_v2_require_finalized_report_artifact()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM public.evidence_assets a WHERE a.id=NEW.evidence_asset_id
     AND a.project_id=NEW.project_id AND a.tenant_id=NEW.tenant_id
     AND a.artifact_status='finalized' AND a.content_hash=NEW.artifact_hash) THEN
  RAISE EXCEPTION 'report export requires a finalized matching project artifact' USING ERRCODE='55000';
 END IF;
 RETURN NEW;
END; $$;
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['report_version_score_snapshots','report_version_retests','report_version_facts','report_version_actions','report_exports'] LOOP EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.geo_v2_reject_report_immutable_update()',t||'_immutable',t);END LOOP; FOREACH t IN ARRAY ARRAY['reports','report_versions','report_exports','report_version_score_snapshots','report_version_retests','report_version_facts','report_version_actions','report_generation_jobs','integration_connectors','notification_recipients','notifications','notification_deliveries','portal_project_settings','portal_report_visibility'] LOOP EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);END LOOP; END; $$;
CREATE TRIGGER report_exports_finalized_artifact_guard BEFORE INSERT ON report_exports
FOR EACH ROW EXECUTE FUNCTION geo_v2_require_finalized_report_artifact();

ALTER FUNCTION geo_v2_enqueue_durable_job_dispatch() OWNER TO geo_v2_job_command_owner; ALTER FUNCTION geo_v2_create_report_generation_job(uuid,uuid,uuid,text,jsonb,text) OWNER TO geo_v2_job_command_owner; ALTER FUNCTION geo_v2_claim_report_generation_job(text,integer,uuid) OWNER TO geo_v2_job_owner; ALTER FUNCTION geo_v2_heartbeat_report_generation_job(uuid,text,uuid,integer) OWNER TO geo_v2_job_owner; ALTER FUNCTION geo_v2_complete_report_generation_job(uuid,text,uuid,uuid) OWNER TO geo_v2_job_owner; ALTER FUNCTION geo_v2_fail_report_generation_job(uuid,text,uuid,text,text,boolean,integer) OWNER TO geo_v2_job_owner; ALTER FUNCTION geo_v2_persist_report_generation_result(uuid,text,uuid,text,text,text,text,text) OWNER TO geo_v2_result_owner; ALTER FUNCTION geo_v2_claim_notification_delivery(text,integer,uuid) OWNER TO geo_v2_job_owner; ALTER FUNCTION geo_v2_heartbeat_notification_delivery(uuid,text,uuid,integer) OWNER TO geo_v2_job_owner; ALTER FUNCTION geo_v2_complete_notification_delivery(uuid,text,uuid,text) OWNER TO geo_v2_job_owner; ALTER FUNCTION geo_v2_fail_notification_delivery(uuid,text,uuid,text,text,boolean,integer) OWNER TO geo_v2_job_owner; ALTER FUNCTION geo_v2_read_portal_reports(uuid) OWNER TO geo_v2_authz_owner; ALTER FUNCTION geo_v2_reject_report_immutable_update() OWNER TO geo_v2_result_owner; ALTER FUNCTION geo_v2_require_finalized_report_artifact() OWNER TO geo_v2_result_owner;
REVOKE ALL ON reports,report_versions,report_exports,report_version_score_snapshots,report_version_retests,report_version_facts,report_version_actions,report_generation_jobs,integration_connectors,notification_recipients,notifications,notification_deliveries,portal_project_settings,portal_report_visibility FROM PUBLIC,geo_v2_runtime,geo_v2_worker;
REVOKE ALL ON FUNCTION geo_v2_create_report_generation_job(uuid,uuid,uuid,text,jsonb,text),geo_v2_claim_report_generation_job(text,integer,uuid),geo_v2_heartbeat_report_generation_job(uuid,text,uuid,integer),geo_v2_complete_report_generation_job(uuid,text,uuid,uuid),geo_v2_fail_report_generation_job(uuid,text,uuid,text,text,boolean,integer),geo_v2_persist_report_generation_result(uuid,text,uuid,text,text,text,text,text),geo_v2_claim_notification_delivery(text,integer,uuid),geo_v2_heartbeat_notification_delivery(uuid,text,uuid,integer),geo_v2_complete_notification_delivery(uuid,text,uuid,text),geo_v2_fail_notification_delivery(uuid,text,uuid,text,text,boolean,integer),geo_v2_read_portal_reports(uuid),geo_v2_reject_report_immutable_update(),geo_v2_require_finalized_report_artifact() FROM PUBLIC;
GRANT SELECT ON reports,report_versions,report_generation_jobs TO geo_v2_job_command_owner; GRANT INSERT,UPDATE ON report_generation_jobs,reports TO geo_v2_job_command_owner; GRANT SELECT,UPDATE ON report_generation_jobs,notification_deliveries TO geo_v2_job_owner; GRANT SELECT ON report_versions TO geo_v2_job_owner; GRANT SELECT,INSERT ON report_versions TO geo_v2_result_owner; GRANT SELECT,UPDATE ON report_generation_jobs TO geo_v2_result_owner; GRANT EXECUTE ON FUNCTION geo_v2_create_report_generation_job(uuid,uuid,uuid,text,jsonb,text),geo_v2_read_portal_reports(uuid) TO geo_v2_runtime; GRANT EXECUTE ON FUNCTION geo_v2_claim_report_generation_job(text,integer,uuid),geo_v2_heartbeat_report_generation_job(uuid,text,uuid,integer),geo_v2_complete_report_generation_job(uuid,text,uuid,uuid),geo_v2_fail_report_generation_job(uuid,text,uuid,text,text,boolean,integer),geo_v2_persist_report_generation_result(uuid,text,uuid,text,text,text,text,text),geo_v2_claim_notification_delivery(text,integer,uuid),geo_v2_heartbeat_notification_delivery(uuid,text,uuid,integer),geo_v2_complete_notification_delivery(uuid,text,uuid,text),geo_v2_fail_notification_delivery(uuid,text,uuid,text,text,boolean,integer) TO geo_v2_worker; GRANT SELECT ON reports,report_versions,report_exports,portal_project_settings,portal_report_visibility TO geo_v2_authz_owner;
CREATE INDEX report_jobs_claim_idx ON report_generation_jobs(priority DESC,next_attempt_at,created_at,id) WHERE status IN ('queued','running'); CREATE INDEX notification_deliveries_claim_idx ON notification_deliveries(next_attempt_at,created_at,id) WHERE status IN ('queued','running');
