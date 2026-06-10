ALTER TABLE collection_run_summaries
  DROP COLUMN IF EXISTS average_duration_ms,
  DROP COLUMN IF EXISTS total_duration_ms;

ALTER TABLE collection_costs
  DROP COLUMN IF EXISTS duration_ms;
