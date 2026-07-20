DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM knowledge_question_generation_specs)
       OR EXISTS (SELECT 1 FROM knowledge_question_dimensions)
       OR EXISTS (SELECT 1 FROM knowledge_question_generation_fact_inputs)
       OR EXISTS (SELECT 1 FROM knowledge_question_generation_entity_inputs)
       OR EXISTS (SELECT 1 FROM knowledge_question_generation_results)
       OR EXISTS (SELECT 1 FROM knowledge_question_candidates)
       OR EXISTS (SELECT 1 FROM knowledge_question_candidate_fact_sources)
       OR EXISTS (SELECT 1 FROM knowledge_question_candidate_entity_sources)
       OR EXISTS (SELECT 1 FROM knowledge_question_sets)
       OR EXISTS (SELECT 1 FROM knowledge_question_set_items)
       OR EXISTS (
            SELECT 1 FROM durable_jobs
            WHERE kind = 'knowledge.question.generate'
       )
       OR EXISTS (
            SELECT 1 FROM monitoring_protocols
            WHERE question_set_id IS NOT NULL
               OR question_set_hash IS NOT NULL
               OR question_set_bound_by IS NOT NULL
               OR question_set_bound_at IS NOT NULL
       )
       OR EXISTS (
            SELECT 1 FROM monitoring_query_suggestions
            WHERE question_set_item_id IS NOT NULL
               OR question_candidate_id IS NOT NULL
       )
       OR EXISTS (
            SELECT 1 FROM monitoring_protocol_queries
            WHERE question_set_item_id IS NOT NULL
               OR question_candidate_id IS NOT NULL
       )
       OR EXISTS (
            SELECT 1 FROM prompt_simulations
            WHERE simulation_purpose = 'geo_question_test'
               OR question_set_id IS NOT NULL
               OR question_set_hash IS NOT NULL
               OR question_set_item_id IS NOT NULL
               OR question_candidate_id IS NOT NULL
       ) THEN
        RAISE EXCEPTION
            'cannot downgrade: QuestionSet generation or binding data exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP TRIGGER IF EXISTS prompt_simulation_geo_evidence_check
    ON prompt_simulations;
DROP TRIGGER IF EXISTS prompt_simulation_evidence_geo_check
    ON prompt_simulation_evidence;
DROP TRIGGER IF EXISTS monitoring_protocol_question_inventory_check
    ON monitoring_protocols;
DROP TRIGGER IF EXISTS monitoring_suggestion_question_inventory_check
    ON monitoring_query_suggestions;
DROP TRIGGER IF EXISTS monitoring_protocol_query_question_inventory_check
    ON monitoring_protocol_queries;
DROP TRIGGER IF EXISTS monitoring_suggestions_question_lineage_guard
    ON monitoring_query_suggestions;
DROP TRIGGER IF EXISTS monitoring_protocol_queries_question_lineage_guard
    ON monitoring_protocol_queries;
DROP TRIGGER IF EXISTS monitoring_suggestions_question_lineage_immutable
    ON monitoring_query_suggestions;
DROP TRIGGER IF EXISTS monitoring_protocol_queries_question_lineage_immutable
    ON monitoring_protocol_queries;

DROP TRIGGER IF EXISTS knowledge_question_generation_spec_kind
    ON knowledge_question_generation_specs;
DROP TRIGGER IF EXISTS knowledge_question_generation_specs_immutable
    ON knowledge_question_generation_specs;
DROP TRIGGER IF EXISTS knowledge_question_generation_specs_delete_guard
    ON knowledge_question_generation_specs;
DROP TRIGGER IF EXISTS knowledge_question_dimensions_insert_guard
    ON knowledge_question_dimensions;
DROP TRIGGER IF EXISTS knowledge_question_dimensions_immutable
    ON knowledge_question_dimensions;
DROP TRIGGER IF EXISTS knowledge_question_fact_inputs_insert_guard
    ON knowledge_question_generation_fact_inputs;
DROP TRIGGER IF EXISTS knowledge_question_fact_inputs_immutable
    ON knowledge_question_generation_fact_inputs;
DROP TRIGGER IF EXISTS knowledge_question_entity_inputs_insert_guard
    ON knowledge_question_generation_entity_inputs;
DROP TRIGGER IF EXISTS knowledge_question_entity_inputs_immutable
    ON knowledge_question_generation_entity_inputs;
DROP TRIGGER IF EXISTS knowledge_question_results_immutable
    ON knowledge_question_generation_results;
DROP TRIGGER IF EXISTS knowledge_question_candidates_contract_guard
    ON knowledge_question_candidates;
DROP TRIGGER IF EXISTS knowledge_question_candidate_fact_sources_immutable
    ON knowledge_question_candidate_fact_sources;
DROP TRIGGER IF EXISTS knowledge_question_candidate_entity_sources_immutable
    ON knowledge_question_candidate_entity_sources;
DROP TRIGGER IF EXISTS knowledge_question_specs_input_inventory_check
    ON knowledge_question_generation_specs;
DROP TRIGGER IF EXISTS knowledge_question_dimensions_input_inventory_check
    ON knowledge_question_dimensions;
DROP TRIGGER IF EXISTS knowledge_question_facts_input_inventory_check
    ON knowledge_question_generation_fact_inputs;
DROP TRIGGER IF EXISTS knowledge_question_entities_input_inventory_check
    ON knowledge_question_generation_entity_inputs;
DROP TRIGGER IF EXISTS knowledge_question_candidates_fact_source_check
    ON knowledge_question_candidates;
DROP TRIGGER IF EXISTS knowledge_question_fact_sources_candidate_check
    ON knowledge_question_candidate_fact_sources;
DROP TRIGGER IF EXISTS knowledge_question_results_count_check
    ON knowledge_question_generation_results;
DROP TRIGGER IF EXISTS knowledge_question_candidates_result_count_check
    ON knowledge_question_candidates;
DROP TRIGGER IF EXISTS knowledge_question_fact_sources_result_count_check
    ON knowledge_question_candidate_fact_sources;
DROP TRIGGER IF EXISTS knowledge_question_sets_contract_guard
    ON knowledge_question_sets;
DROP TRIGGER IF EXISTS knowledge_question_set_items_insert_guard
    ON knowledge_question_set_items;
DROP TRIGGER IF EXISTS knowledge_question_set_items_immutable
    ON knowledge_question_set_items;
DROP TRIGGER IF EXISTS knowledge_question_sets_inventory_check
    ON knowledge_question_sets;
DROP TRIGGER IF EXISTS knowledge_question_set_items_inventory_check
    ON knowledge_question_set_items;

CREATE OR REPLACE FUNCTION geo_protect_monitoring_protocol() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'monitoring protocols cannot be deleted' USING ERRCODE = '55000';
    END IF;
    IF OLD.status = 'frozen' THEN
        RAISE EXCEPTION 'frozen monitoring protocols are immutable' USING ERRCODE = '55000';
    END IF;
    IF NOT ((OLD.status = 'draft' AND NEW.status IN ('draft', 'approved'))
            OR (OLD.status = 'approved' AND NEW.status IN ('approved', 'frozen'))) THEN
        RAISE EXCEPTION 'invalid monitoring protocol transition' USING ERRCODE = '23514';
    END IF;
    IF NEW.status IN ('approved', 'frozen') AND NOT EXISTS (
        SELECT 1 FROM monitoring_protocol_queries q
        WHERE q.protocol_id = NEW.id AND q.project_id = NEW.project_id
    ) THEN
        RAISE EXCEPTION 'approved monitoring protocols require an approved query'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION geo_assert_prompt_simulation_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM product_entities AS entity
        WHERE entity.id = NEW.primary_brand_entity_id
          AND entity.project_id = NEW.project_id
          AND entity.entity_type = 'brand' AND entity.status = 'active'
    ) OR NOT EXISTS (
        SELECT 1 FROM product_entities AS entity
        WHERE entity.id = NEW.product_entity_id
          AND entity.project_id = NEW.project_id
          AND entity.entity_type = 'product' AND entity.status = 'active'
    ) THEN
        RAISE EXCEPTION 'prompt simulation subjects must be active brand and product entities'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.destination_policy_version_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM destination_policy_versions AS policy
        WHERE policy.id = NEW.destination_policy_version_id
          AND policy.project_id = NEW.project_id
          AND policy.destination_id = NEW.destination_id
    ) THEN
        RAISE EXCEPTION 'prompt simulation policy does not belong to its destination'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.binding_contract_version <> 'opportunity-binding-v2' THEN
        RAISE EXCEPTION 'new prompt simulations require an Opportunity binding'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM current_opportunity_prompt_release_bindings AS binding
        JOIN current_generation_template_release_states AS state
          ON state.template_release_id = binding.template_release_id
         AND state.project_id = binding.project_id
        WHERE binding.id = NEW.binding_id AND binding.project_id = NEW.project_id
          AND binding.campaign_id = NEW.campaign_id
          AND binding.opportunity_id = NEW.opportunity_id
          AND binding.destination_id = NEW.destination_id
          AND binding.binding_version = NEW.binding_version
          AND binding.binding_state = 'bound'
          AND binding.template_release_id = NEW.template_release_id
          AND binding.skill_version_id = NEW.template_skill_version_id
          AND binding.release_number = NEW.template_release_number
          AND binding.release_hash = NEW.template_release_hash
          AND state.status = 'approved'
    ) THEN
        RAISE EXCEPTION 'prompt simulation binding is stale, unbound, or not approved'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION geo_assert_new_prompt_simulation_result() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.lineage_contract_version = 'opportunity-binding-v2' THEN
        RETURN NEW;
    END IF;
    IF NEW.lineage_contract_version = 'legacy-v1' AND EXISTS (
        SELECT 1
        FROM prompt_simulations AS simulation
        JOIN prompt_simulation_job_specs AS spec
          ON spec.simulation_id = simulation.id
         AND spec.project_id = simulation.project_id
        WHERE simulation.id = NEW.simulation_id
          AND simulation.project_id = NEW.project_id
          AND spec.job_id = NEW.generated_by_job_id
          AND simulation.binding_contract_version = 'legacy-v1'
          AND simulation.campaign_id IS NULL
          AND simulation.opportunity_id IS NULL
          AND spec.campaign_id IS NULL
          AND spec.opportunity_id IS NULL
    ) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'prompt simulation result lineage is not exact'
        USING ERRCODE = '23514';
END;
$$;

DROP FUNCTION IF EXISTS geo_assert_question_dimension();
DROP FUNCTION IF EXISTS geo_assert_question_fact_input();
DROP FUNCTION IF EXISTS geo_assert_question_entity_input();
DROP FUNCTION IF EXISTS geo_assert_question_generation_inputs();
DROP FUNCTION IF EXISTS geo_protect_question_candidate();
DROP FUNCTION IF EXISTS geo_assert_question_candidate_fact_source();
DROP FUNCTION IF EXISTS geo_assert_question_generation_result_counts();
DROP FUNCTION IF EXISTS geo_question_candidate_source_lineage_hash(uuid);
DROP FUNCTION IF EXISTS geo_question_candidate_sources_current(uuid);
DROP FUNCTION IF EXISTS geo_question_set_content_hash(uuid);
DROP FUNCTION IF EXISTS geo_assert_question_set_item();
DROP FUNCTION IF EXISTS geo_assert_question_set_inventory();
DROP FUNCTION IF EXISTS geo_protect_question_set();
DROP FUNCTION IF EXISTS geo_assert_protocol_question_lineage();
DROP FUNCTION IF EXISTS geo_protocol_question_inventory_complete(uuid);
DROP FUNCTION IF EXISTS geo_assert_protocol_question_inventory();
DROP FUNCTION IF EXISTS geo_protect_protocol_question_lineage();
DROP FUNCTION IF EXISTS geo_assert_geo_simulation_evidence();

ALTER TABLE prompt_simulations
    DROP CONSTRAINT prompt_simulations_question_item_fkey,
    DROP CONSTRAINT prompt_simulations_question_set_fkey,
    DROP CONSTRAINT prompt_simulations_question_set_hash_check,
    DROP CONSTRAINT prompt_simulations_question_shape_check,
    DROP COLUMN question_candidate_id,
    DROP COLUMN question_set_item_id,
    DROP COLUMN question_set_hash,
    DROP COLUMN question_set_id,
    DROP COLUMN simulation_purpose;

ALTER TABLE monitoring_protocol_queries
    DROP CONSTRAINT monitoring_protocol_queries_question_lineage_fkey,
    DROP CONSTRAINT monitoring_protocol_queries_question_lineage_pair_check,
    DROP CONSTRAINT monitoring_protocol_queries_question_item_key,
    DROP COLUMN question_candidate_id,
    DROP COLUMN question_set_item_id;

ALTER TABLE monitoring_query_suggestions
    DROP CONSTRAINT monitoring_suggestions_question_lineage_fkey,
    DROP CONSTRAINT monitoring_suggestions_question_lineage_pair_check,
    DROP CONSTRAINT monitoring_suggestions_question_item_key,
    DROP COLUMN question_candidate_id,
    DROP COLUMN question_set_item_id;

ALTER TABLE monitoring_protocols
    DROP CONSTRAINT monitoring_protocols_question_set_fkey,
    DROP CONSTRAINT monitoring_protocols_question_set_shape_check,
    DROP COLUMN question_set_bound_at,
    DROP COLUMN question_set_bound_by,
    DROP COLUMN question_set_hash,
    DROP COLUMN question_set_id;

DROP TABLE knowledge_question_set_items;
DROP TABLE knowledge_question_sets;
DROP TABLE knowledge_question_candidate_entity_sources;
DROP TABLE knowledge_question_candidate_fact_sources;
DROP TABLE knowledge_question_candidates;
DROP TABLE knowledge_question_generation_results;
DROP TABLE knowledge_question_generation_entity_inputs;
DROP TABLE knowledge_question_generation_fact_inputs;
DROP TABLE knowledge_question_dimensions;
DROP TABLE knowledge_question_generation_specs;
