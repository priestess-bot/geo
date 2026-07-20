-- Recover the Document identity from the existing relational Chunk edge only.
ALTER TABLE knowledge_fact_candidates ADD COLUMN document_id uuid;
UPDATE knowledge_fact_candidates AS fact
SET document_id = chunk.document_id
FROM knowledge_chunks AS chunk
WHERE chunk.id = fact.chunk_id
  AND chunk.project_id = fact.project_id
  AND chunk.pipeline_run_id = fact.pipeline_run_id
  AND chunk.source_id = fact.source_id;
ALTER TABLE knowledge_fact_candidates ALTER COLUMN document_id SET NOT NULL;

-- Exact identities let every hop in Source -> Run -> Document -> Chunk -> Fact
-- be represented by composite foreign keys instead of application convention.
ALTER TABLE knowledge_sources
    ADD CONSTRAINT knowledge_sources_exact_content_key
        UNIQUE (id, project_id, content_hash);
ALTER TABLE knowledge_pipeline_runs
    ADD CONSTRAINT knowledge_pipeline_runs_exact_source_key
        UNIQUE (id, project_id, source_id);
ALTER TABLE knowledge_documents
    ADD CONSTRAINT knowledge_documents_exact_context_key
        UNIQUE (id, project_id, pipeline_run_id, source_id),
    ADD CONSTRAINT knowledge_documents_exact_hash_key
        UNIQUE (id, project_id, pipeline_run_id, source_id, cleaned_text_hash),
    ADD CONSTRAINT knowledge_documents_exact_run_fkey
        FOREIGN KEY (pipeline_run_id, project_id, source_id)
        REFERENCES knowledge_pipeline_runs(id, project_id, source_id);
ALTER TABLE knowledge_chunks
    ADD CONSTRAINT knowledge_chunks_exact_context_key
        UNIQUE (id, project_id, pipeline_run_id, source_id, document_id),
    ADD CONSTRAINT knowledge_chunks_exact_hash_key
        UNIQUE (
            id, project_id, pipeline_run_id, source_id, document_id, text_hash
        ),
    ADD CONSTRAINT knowledge_chunks_exact_run_fkey
        FOREIGN KEY (pipeline_run_id, project_id, source_id)
        REFERENCES knowledge_pipeline_runs(id, project_id, source_id),
    ADD CONSTRAINT knowledge_chunks_exact_document_fkey
        FOREIGN KEY (document_id, project_id, pipeline_run_id, source_id)
        REFERENCES knowledge_documents(id, project_id, pipeline_run_id, source_id);
ALTER TABLE knowledge_fact_candidates
    ADD CONSTRAINT knowledge_facts_exact_context_key
        UNIQUE (
            id, project_id, pipeline_run_id, source_id, document_id, chunk_id
        ),
    ADD CONSTRAINT knowledge_facts_exact_hash_key
        UNIQUE (
            id, project_id, pipeline_run_id, source_id, document_id, chunk_id,
            statement_hash
        ),
    ADD CONSTRAINT knowledge_facts_exact_run_fkey
        FOREIGN KEY (pipeline_run_id, project_id, source_id)
        REFERENCES knowledge_pipeline_runs(id, project_id, source_id),
    ADD CONSTRAINT knowledge_facts_exact_document_fkey
        FOREIGN KEY (document_id, project_id, pipeline_run_id, source_id)
        REFERENCES knowledge_documents(id, project_id, pipeline_run_id, source_id),
    ADD CONSTRAINT knowledge_facts_exact_chunk_fkey
        FOREIGN KEY (
            chunk_id, project_id, pipeline_run_id, source_id, document_id
        ) REFERENCES knowledge_chunks(
            id, project_id, pipeline_run_id, source_id, document_id
        );

CREATE INDEX knowledge_documents_exact_run_idx
ON knowledge_documents (pipeline_run_id, project_id, source_id);
CREATE INDEX knowledge_chunks_exact_run_idx
ON knowledge_chunks (pipeline_run_id, project_id, source_id);
CREATE INDEX knowledge_chunks_exact_document_idx
ON knowledge_chunks (document_id, project_id, pipeline_run_id, source_id);
CREATE INDEX knowledge_facts_exact_run_idx
ON knowledge_fact_candidates (pipeline_run_id, project_id, source_id);
CREATE INDEX knowledge_facts_exact_document_idx
ON knowledge_fact_candidates (document_id, project_id, pipeline_run_id, source_id);
CREATE INDEX knowledge_facts_exact_chunk_idx
ON knowledge_fact_candidates (
    chunk_id, project_id, pipeline_run_id, source_id, document_id
);

-- Existing approved facts cannot be claimed as verified after the fact. New
-- verified rows must use the current relational contract.
DROP TRIGGER evidence_items_immutable ON evidence_items;
ALTER TABLE evidence_items
    ADD COLUMN fact_lineage_status text NOT NULL DEFAULT 'not_applicable';
UPDATE evidence_items
SET fact_lineage_status = 'legacy_unverified'
WHERE item_type = 'approved_fact';
ALTER TABLE evidence_items
    ADD CONSTRAINT evidence_items_fact_lineage_status_check CHECK (
        fact_lineage_status IN ('not_applicable', 'legacy_unverified', 'verified')
    ),
    ADD CONSTRAINT evidence_items_fact_lineage_type_check CHECK (
        (item_type = 'approved_fact'
            AND fact_lineage_status IN ('legacy_unverified', 'verified'))
        OR (item_type <> 'approved_fact'
            AND fact_lineage_status = 'not_applicable')
    ),
    ADD CONSTRAINT evidence_items_exact_lineage_identity_key
        UNIQUE (id, project_id, source_id, source_revision_value, snapshot_hash);
CREATE TRIGGER evidence_items_immutable
BEFORE UPDATE OR DELETE ON evidence_items
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

CREATE TABLE knowledge_fact_evidence_lineages (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    pipeline_run_id uuid NOT NULL,
    knowledge_source_id uuid NOT NULL,
    knowledge_document_id uuid NOT NULL,
    knowledge_chunk_id uuid NOT NULL,
    knowledge_fact_id uuid NOT NULL,
    evidence_item_id uuid NOT NULL,
    evidence_title text NOT NULL CHECK (btrim(evidence_title) <> ''),
    promoted_by uuid NOT NULL REFERENCES identities(id),
    promoted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    idempotency_key text NOT NULL CHECK (
        btrim(idempotency_key) <> '' AND length(idempotency_key) <= 200
    ),
    promotion_request_hash text NOT NULL
        CHECK (promotion_request_hash ~ '^[0-9a-f]{64}$'),
    source_content_hash text NOT NULL CHECK (source_content_hash ~ '^[0-9a-f]{64}$'),
    document_cleaned_text_hash text NOT NULL
        CHECK (document_cleaned_text_hash ~ '^[0-9a-f]{64}$'),
    chunk_text_hash text NOT NULL CHECK (chunk_text_hash ~ '^[0-9a-f]{64}$'),
    fact_statement_hash text NOT NULL CHECK (fact_statement_hash ~ '^[0-9a-f]{64}$'),
    evidence_snapshot_hash text NOT NULL
        CHECK (evidence_snapshot_hash ~ '^[0-9a-f]{64}$'),
    lineage_contract_version text NOT NULL CHECK (
        lineage_contract_version IN (
            'legacy-relational-v1', 'knowledge-fact-evidence-v1'
        )
    ),
    evidence_source_id uuid GENERATED ALWAYS AS (
        CASE lineage_contract_version
            WHEN 'legacy-relational-v1' THEN knowledge_source_id
            ELSE knowledge_fact_id
        END
    ) STORED,
    evidence_source_revision_value text GENERATED ALWAYS AS (
        CASE lineage_contract_version
            WHEN 'legacy-relational-v1' THEN source_content_hash
            ELSE fact_statement_hash
        END
    ) STORED,
    PRIMARY KEY (project_id, knowledge_fact_id, evidence_item_id),
    UNIQUE (project_id, evidence_item_id),
    UNIQUE (project_id, idempotency_key),
    FOREIGN KEY (knowledge_source_id, project_id, source_content_hash)
        REFERENCES knowledge_sources(id, project_id, content_hash),
    FOREIGN KEY (pipeline_run_id, project_id, knowledge_source_id)
        REFERENCES knowledge_pipeline_runs(id, project_id, source_id),
    FOREIGN KEY (
        knowledge_document_id, project_id, pipeline_run_id,
        knowledge_source_id, document_cleaned_text_hash
    ) REFERENCES knowledge_documents(
        id, project_id, pipeline_run_id, source_id, cleaned_text_hash
    ),
    FOREIGN KEY (
        knowledge_chunk_id, project_id, pipeline_run_id, knowledge_source_id,
        knowledge_document_id, chunk_text_hash
    ) REFERENCES knowledge_chunks(
        id, project_id, pipeline_run_id, source_id, document_id, text_hash
    ),
    FOREIGN KEY (
        knowledge_fact_id, project_id, pipeline_run_id, knowledge_source_id,
        knowledge_document_id, knowledge_chunk_id, fact_statement_hash
    ) REFERENCES knowledge_fact_candidates(
        id, project_id, pipeline_run_id, source_id, document_id, chunk_id,
        statement_hash
    ),
    FOREIGN KEY (
        evidence_item_id, project_id, evidence_source_id,
        evidence_source_revision_value, evidence_snapshot_hash
    ) REFERENCES evidence_items(
        id, project_id, source_id, source_revision_value, snapshot_hash
    )
);

CREATE INDEX knowledge_fact_lineages_source_idx
ON knowledge_fact_evidence_lineages (
    knowledge_source_id, project_id, source_content_hash
);
CREATE INDEX knowledge_fact_lineages_run_idx
ON knowledge_fact_evidence_lineages (
    pipeline_run_id, project_id, knowledge_source_id
);
CREATE INDEX knowledge_fact_lineages_document_idx
ON knowledge_fact_evidence_lineages (
    knowledge_document_id, project_id, pipeline_run_id, knowledge_source_id,
    document_cleaned_text_hash
);
CREATE INDEX knowledge_fact_lineages_chunk_idx
ON knowledge_fact_evidence_lineages (
    knowledge_chunk_id, project_id, pipeline_run_id, knowledge_source_id,
    knowledge_document_id, chunk_text_hash
);
CREATE INDEX knowledge_fact_lineages_fact_idx
ON knowledge_fact_evidence_lineages (
    knowledge_fact_id, project_id, pipeline_run_id, knowledge_source_id,
    knowledge_document_id, knowledge_chunk_id, fact_statement_hash
);
CREATE INDEX knowledge_fact_lineages_evidence_idx
ON knowledge_fact_evidence_lineages (
    evidence_item_id, project_id, evidence_source_id,
    evidence_source_revision_value, evidence_snapshot_hash
);
CREATE INDEX knowledge_fact_lineages_promoter_idx
ON knowledge_fact_evidence_lineages (promoted_by, promoted_at DESC);
CREATE UNIQUE INDEX knowledge_fact_lineages_current_fact_key
ON knowledge_fact_evidence_lineages (project_id, knowledge_fact_id)
WHERE lineage_contract_version = 'knowledge-fact-evidence-v1';

-- Backfill only one-to-one relationships proven by columns already present in
-- the old schema. locator JSON is deliberately not consulted.
WITH relational_candidates AS (
    SELECT
        evidence.project_id,
        fact.pipeline_run_id,
        fact.source_id AS knowledge_source_id,
        fact.document_id AS knowledge_document_id,
        fact.chunk_id AS knowledge_chunk_id,
        fact.id AS knowledge_fact_id,
        evidence.id AS evidence_item_id,
        COALESCE(
            NULLIF(btrim(evidence.public_source_title), ''),
            NULLIF(btrim(evidence.citation_label), ''),
            source.title
        ) AS evidence_title,
        COALESCE(fact.reviewed_by, source.created_by) AS promoted_by,
        COALESCE(fact.reviewed_at, evidence.created_at) AS promoted_at,
        source.content_hash AS source_content_hash,
        document.cleaned_text_hash AS document_cleaned_text_hash,
        chunk.text_hash AS chunk_text_hash,
        fact.statement_hash AS fact_statement_hash,
        evidence.snapshot_hash AS evidence_snapshot_hash,
        count(*) OVER (PARTITION BY evidence.project_id, evidence.id) AS evidence_matches,
        count(*) OVER (PARTITION BY fact.project_id, fact.id) AS fact_matches
    FROM evidence_items AS evidence
    JOIN knowledge_fact_candidates AS fact
      ON fact.project_id = evidence.project_id
     AND fact.source_id = evidence.source_id
     AND fact.statement_hash = evidence.snapshot_hash
     AND fact.statement = evidence.snapshot_text
    JOIN knowledge_chunks AS chunk
      ON chunk.id = fact.chunk_id AND chunk.project_id = fact.project_id
     AND chunk.pipeline_run_id = fact.pipeline_run_id
     AND chunk.source_id = fact.source_id AND chunk.document_id = fact.document_id
    JOIN knowledge_documents AS document
      ON document.id = fact.document_id AND document.project_id = fact.project_id
     AND document.pipeline_run_id = fact.pipeline_run_id
     AND document.source_id = fact.source_id
    JOIN knowledge_pipeline_runs AS run
      ON run.id = fact.pipeline_run_id AND run.project_id = fact.project_id
     AND run.source_id = fact.source_id
    JOIN knowledge_sources AS source
      ON source.id = fact.source_id AND source.project_id = fact.project_id
    WHERE evidence.item_type = 'approved_fact'
      AND evidence.source_revision_kind = 'content_hash'
      AND evidence.source_revision_value = source.content_hash
      AND source.status = 'ready' AND source.content_hash IS NOT NULL
      AND source.raw_content IS NOT NULL
      AND encode(digest(source.raw_content, 'sha256'), 'hex') = source.content_hash
      AND run.status = 'succeeded'
      AND encode(digest(convert_to(document.cleaned_text, 'UTF8'), 'sha256'), 'hex')
            = document.cleaned_text_hash
      AND chunk.status = 'active'
      AND encode(digest(convert_to(chunk.text, 'UTF8'), 'sha256'), 'hex') = chunk.text_hash
      AND fact.status = 'approved'
      AND encode(digest(convert_to(fact.statement, 'UTF8'), 'sha256'), 'hex')
            = fact.statement_hash
)
INSERT INTO knowledge_fact_evidence_lineages (
    project_id, pipeline_run_id, knowledge_source_id, knowledge_document_id,
    knowledge_chunk_id, knowledge_fact_id, evidence_item_id, evidence_title,
    promoted_by, promoted_at, idempotency_key, promotion_request_hash,
    source_content_hash, document_cleaned_text_hash,
    chunk_text_hash, fact_statement_hash, evidence_snapshot_hash,
    lineage_contract_version
)
SELECT project_id, pipeline_run_id, knowledge_source_id, knowledge_document_id,
       knowledge_chunk_id, knowledge_fact_id, evidence_item_id, evidence_title,
       promoted_by, promoted_at,
       'legacy-relational-v1:' || evidence_item_id::text,
       encode(
           digest(
               convert_to('legacy-relational-v1:' || evidence_item_id::text, 'UTF8'),
               'sha256'
           ),
           'hex'
       ),
       source_content_hash, document_cleaned_text_hash,
       chunk_text_hash, fact_statement_hash, evidence_snapshot_hash,
       'legacy-relational-v1'
FROM relational_candidates
WHERE evidence_matches = 1 AND fact_matches = 1;

CREATE FUNCTION geo_assert_fact_evidence_lineage() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.lineage_contract_version <> 'knowledge-fact-evidence-v1' THEN
        RAISE EXCEPTION 'new Fact Evidence lineage must use the current contract'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM knowledge_sources AS source
        JOIN knowledge_pipeline_runs AS run
          ON run.id = NEW.pipeline_run_id AND run.project_id = NEW.project_id
         AND run.source_id = source.id
        JOIN knowledge_documents AS document
          ON document.id = NEW.knowledge_document_id
         AND document.project_id = NEW.project_id
         AND document.pipeline_run_id = run.id
         AND document.source_id = source.id
        JOIN knowledge_chunks AS chunk
          ON chunk.id = NEW.knowledge_chunk_id
         AND chunk.project_id = NEW.project_id
         AND chunk.pipeline_run_id = run.id
         AND chunk.source_id = source.id
         AND chunk.document_id = document.id
        JOIN knowledge_fact_candidates AS fact
          ON fact.id = NEW.knowledge_fact_id
         AND fact.project_id = NEW.project_id
         AND fact.pipeline_run_id = run.id
         AND fact.source_id = source.id
         AND fact.document_id = document.id
         AND fact.chunk_id = chunk.id
        JOIN evidence_items AS evidence
          ON evidence.id = NEW.evidence_item_id
         AND evidence.project_id = NEW.project_id
        WHERE source.id = NEW.knowledge_source_id
          AND source.status = 'ready' AND source.raw_content IS NOT NULL
          AND source.content_hash = NEW.source_content_hash
          AND encode(digest(source.raw_content, 'sha256'), 'hex') = source.content_hash
          AND run.status = 'succeeded' AND run.completed_at IS NOT NULL
          AND document.cleaned_text_hash = NEW.document_cleaned_text_hash
          AND encode(digest(convert_to(document.cleaned_text, 'UTF8'), 'sha256'), 'hex')
                = document.cleaned_text_hash
          AND chunk.status = 'active' AND chunk.text_hash = NEW.chunk_text_hash
          AND chunk.char_count = char_length(chunk.text)
          AND encode(digest(convert_to(chunk.text, 'UTF8'), 'sha256'), 'hex')
                = chunk.text_hash
          AND fact.status = 'approved' AND fact.reviewed_by IS NOT NULL
          AND fact.reviewed_at IS NOT NULL
          AND fact.statement_hash = NEW.fact_statement_hash
          AND encode(digest(convert_to(fact.statement, 'UTF8'), 'sha256'), 'hex')
                = fact.statement_hash
          AND evidence.item_type = 'approved_fact'
          AND evidence.fact_lineage_status = 'verified'
          AND evidence.source_id = fact.id
          AND evidence.source_revision_kind = 'content_hash'
          AND evidence.source_revision_value = fact.statement_hash
          AND evidence.snapshot_text = fact.statement
          AND evidence.snapshot_hash = NEW.evidence_snapshot_hash
          AND encode(digest(convert_to(evidence.snapshot_text, 'UTF8'), 'sha256'), 'hex')
                = evidence.snapshot_hash
          AND evidence.usage_rights IN ('owned', 'licensed', 'public_reference')
          AND evidence.confidentiality <> 'restricted'
          AND (
              evidence.usage_rights <> 'public_reference'
              OR (
                  btrim(COALESCE(evidence.public_source_url, '')) <> ''
                  AND btrim(COALESCE(evidence.public_source_title, '')) <> ''
              )
          )
    ) THEN
        RAISE EXCEPTION 'Fact Evidence lineage is not an exact verified source chain'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_new_approved_fact_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.item_type = 'approved_fact' AND (
        NEW.fact_lineage_status <> 'verified'
        OR NEW.source_revision_kind <> 'content_hash'
        OR NEW.snapshot_text IS NULL
    ) THEN
        RAISE EXCEPTION 'new approved Fact Evidence must request verified relational lineage'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_require_approved_fact_evidence_lineage() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.item_type = 'approved_fact' AND NOT EXISTS (
        SELECT 1 FROM knowledge_fact_evidence_lineages AS lineage
        WHERE lineage.project_id = NEW.project_id
          AND lineage.evidence_item_id = NEW.id
          AND lineage.knowledge_fact_id = NEW.source_id
          AND lineage.fact_statement_hash = NEW.source_revision_value
          AND lineage.evidence_snapshot_hash = NEW.snapshot_hash
          AND lineage.lineage_contract_version = 'knowledge-fact-evidence-v1'
    ) THEN
        RAISE EXCEPTION 'verified approved Fact Evidence requires lineage in the same transaction'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_protect_fact_evidence_lineage() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Fact Evidence lineage is immutable' USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION geo_protect_promoted_knowledge_fact() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM knowledge_fact_evidence_lineages AS lineage
        WHERE lineage.project_id = OLD.project_id
          AND lineage.knowledge_fact_id = OLD.id
    ) THEN
        RAISE EXCEPTION 'promoted knowledge Facts are immutable' USING ERRCODE = '55000';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE TRIGGER knowledge_fact_evidence_lineage_insert_guard
BEFORE INSERT ON knowledge_fact_evidence_lineages
FOR EACH ROW EXECUTE FUNCTION geo_assert_fact_evidence_lineage();
CREATE TRIGGER knowledge_fact_evidence_lineages_immutable
BEFORE UPDATE OR DELETE ON knowledge_fact_evidence_lineages
FOR EACH ROW EXECUTE FUNCTION geo_protect_fact_evidence_lineage();
CREATE TRIGGER knowledge_facts_promoted_immutable
BEFORE UPDATE OR DELETE ON knowledge_fact_candidates
FOR EACH ROW EXECUTE FUNCTION geo_protect_promoted_knowledge_fact();
CREATE TRIGGER evidence_items_new_fact_contract
BEFORE INSERT ON evidence_items
FOR EACH ROW EXECUTE FUNCTION geo_assert_new_approved_fact_evidence();
CREATE CONSTRAINT TRIGGER evidence_items_require_fact_lineage
AFTER INSERT ON evidence_items
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_require_approved_fact_evidence_lineage();

CREATE FUNCTION geo_assert_evidence_pack_item_lineage() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM evidence_items AS evidence
        WHERE evidence.id = NEW.evidence_item_id
          AND evidence.project_id = NEW.project_id
          AND evidence.item_type = 'approved_fact'
          AND (
              evidence.fact_lineage_status <> 'verified'
              OR NOT EXISTS (
                  SELECT 1 FROM knowledge_fact_evidence_lineages AS lineage
                  WHERE lineage.project_id = evidence.project_id
                    AND lineage.evidence_item_id = evidence.id
                    AND lineage.lineage_contract_version = 'knowledge-fact-evidence-v1'
              )
          )
    ) THEN
        RAISE EXCEPTION 'Evidence Packs require verified Fact lineage'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER evidence_pack_items_fact_lineage_guard
BEFORE INSERT ON evidence_pack_items
FOR EACH ROW EXECUTE FUNCTION geo_assert_evidence_pack_item_lineage();

CREATE OR REPLACE FUNCTION geo_protect_evidence_pack_attempt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'evidence pack attempts are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.status <> 'building' THEN
        IF OLD.status IN ('ready', 'needs_evidence', 'blocked') AND NEW.status = 'superseded'
           AND NEW.superseded_by_attempt_id IS NOT NULL AND NEW.superseded_at IS NOT NULL
           AND (NEW.id, NEW.project_id, NEW.brief_version_id, NEW.attempt_number,
                NEW.failure_reason, NEW.pack_hash, NEW.created_at, NEW.completed_at)
               IS NOT DISTINCT FROM
               (OLD.id, OLD.project_id, OLD.brief_version_id, OLD.attempt_number,
                OLD.failure_reason, OLD.pack_hash, OLD.created_at, OLD.completed_at) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'terminal evidence pack attempts are immutable; create a new attempt'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.status = 'superseded' THEN
        RAISE EXCEPTION 'a building evidence pack cannot be superseded'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'ready' THEN
        IF NOT EXISTS (
            SELECT 1 FROM evidence_pack_items AS item
            WHERE item.pack_attempt_id = NEW.id AND item.project_id = NEW.project_id
        ) OR EXISTS (
            SELECT 1
            FROM evidence_pack_items AS item
            JOIN evidence_items AS evidence
              ON evidence.id = item.evidence_item_id
             AND evidence.project_id = item.project_id
            WHERE item.pack_attempt_id = NEW.id AND item.project_id = NEW.project_id
              AND (
                  evidence.usage_rights IN ('unknown', 'restricted')
                  OR evidence.confidentiality = 'restricted'
                  OR (
                      evidence.item_type = 'approved_fact'
                      AND (
                          evidence.fact_lineage_status <> 'verified'
                          OR NOT EXISTS (
                              SELECT 1 FROM knowledge_fact_evidence_lineages AS lineage
                              WHERE lineage.project_id = evidence.project_id
                                AND lineage.evidence_item_id = evidence.id
                                AND lineage.lineage_contract_version =
                                    'knowledge-fact-evidence-v1'
                          )
                      )
                  )
              )
        ) THEN
            RAISE EXCEPTION 'ready Evidence Packs require eligible verified Evidence'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

ALTER TABLE knowledge_fact_evidence_lineages ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_fact_evidence_lineages FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON knowledge_fact_evidence_lineages
    USING (project_id = ANY(geo_current_project_ids()))
    WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE ALL ON knowledge_fact_evidence_lineages
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT, INSERT ON knowledge_fact_evidence_lineages TO geo_app, geo_worker;
GRANT SELECT ON knowledge_fact_evidence_lineages TO geo_readonly;
REVOKE ALL ON FUNCTION geo_assert_fact_evidence_lineage(),
    geo_assert_new_approved_fact_evidence(),
    geo_require_approved_fact_evidence_lineage(),
    geo_protect_fact_evidence_lineage(),
    geo_protect_promoted_knowledge_fact(),
    geo_assert_evidence_pack_item_lineage()
FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_assert_fact_evidence_lineage(),
    geo_assert_new_approved_fact_evidence(),
    geo_require_approved_fact_evidence_lineage(),
    geo_protect_fact_evidence_lineage(),
    geo_protect_promoted_knowledge_fact(),
    geo_assert_evidence_pack_item_lineage()
FROM geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_assert_fact_evidence_lineage(),
    geo_assert_new_approved_fact_evidence(),
    geo_require_approved_fact_evidence_lineage(),
    geo_protect_fact_evidence_lineage(),
    geo_protect_promoted_knowledge_fact(),
    geo_assert_evidence_pack_item_lineage()
TO geo_app, geo_worker;
