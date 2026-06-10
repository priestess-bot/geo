ALTER TABLE collection_costs
  ADD COLUMN IF NOT EXISTS duration_ms integer NOT NULL DEFAULT 0;

ALTER TABLE collection_run_summaries
  ADD COLUMN IF NOT EXISTS total_duration_ms integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS average_duration_ms integer NOT NULL DEFAULT 0;
