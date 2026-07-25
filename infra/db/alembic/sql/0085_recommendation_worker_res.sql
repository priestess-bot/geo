-- The production parent handler owns this immutable projection.  Keep every
-- Recommendation lifecycle and downstream-draft table outside this grant.
GRANT INSERT ON recommendation_generation_results TO geo_worker;
