REVOKE EXECUTE ON FUNCTION geo_materialize_recommendation_generation_draft(
    uuid, uuid, uuid, bigint
) FROM geo_worker;
DROP FUNCTION geo_materialize_recommendation_generation_draft(
    uuid, uuid, uuid, bigint
);

ALTER TABLE recommendation_evidence_bindings
    DROP CONSTRAINT recommendation_evidence_bindings_evidence_kind_check,
    ADD CONSTRAINT recommendation_evidence_bindings_evidence_kind_check CHECK (
        evidence_kind IN (
            'observation', 'metric_comparison', 'fact', 'rule', 'prompt_release',
            'model_call', 'content', 'question', 'surface'
        )
    );
