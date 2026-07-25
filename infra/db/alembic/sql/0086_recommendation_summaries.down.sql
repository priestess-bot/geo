DROP FUNCTION geo_resolve_recommendation_evidence(uuid, text, text);
ALTER FUNCTION geo_resolve_recommendation_evidence_pre_0086(uuid, text, text)
    RENAME TO geo_resolve_recommendation_evidence;
GRANT EXECUTE ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    TO geo_app, geo_worker;
